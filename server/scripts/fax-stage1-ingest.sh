#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SQL_DIR=$(cd "$SCRIPT_DIR/../fax-stage1" && pwd)

usage() {
  echo "Usage: $0 --fax-id ID --pdf FILE --database-url URL [--work-dir DIR] [--skip-vision]" >&2
  exit 64
}

FAX_ID=""
PDF_PATH=""
DATABASE_URL_VALUE="${DATABASE_URL:-}"
WORK_DIR=""
SKIP_VISION=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fax-id) FAX_ID=${2:-}; shift 2 ;;
    --pdf) PDF_PATH=${2:-}; shift 2 ;;
    --database-url) DATABASE_URL_VALUE=${2:-}; shift 2 ;;
    --work-dir) WORK_DIR=${2:-}; shift 2 ;;
    --skip-vision) SKIP_VISION=true; shift ;;
    *) usage ;;
  esac
done

[[ "$FAX_ID" =~ ^[0-9]+$ ]] || usage
[[ -f "$PDF_PATH" ]] || { echo "PDF not found: $PDF_PATH" >&2; exit 66; }
[[ -n "$DATABASE_URL_VALUE" ]] || { echo "DATABASE_URL or --database-url is required" >&2; exit 64; }

for tool in psql pdfinfo pdftoppm tesseract jq curl base64; do
  command -v "$tool" >/dev/null || { echo "Required executable missing: $tool" >&2; exit 69; }
done

PDF_PATH=$(cd "$(dirname "$PDF_PATH")" && pwd)/$(basename "$PDF_PATH")
if command -v sha256sum >/dev/null; then
  SOURCE_SHA=$(sha256sum "$PDF_PATH" | awk '{print $1}')
else
  SOURCE_SHA=$(shasum -a 256 "$PDF_PATH" | awk '{print $1}')
fi
PAGE_COUNT=$(pdfinfo "$PDF_PATH" | awk -F: '/^Pages:/ {gsub(/[[:space:]]/, "", $2); print $2}')
[[ "$PAGE_COUNT" =~ ^[1-9][0-9]*$ ]] || { echo "Could not determine PDF page count" >&2; exit 65; }

if [[ -z "$WORK_DIR" ]]; then
  WORK_DIR="${CAL_FAX_STAGE1_DIR:-/tmp/cal-fax-stage1}/$FAX_ID/$SOURCE_SHA"
fi
mkdir -p "$WORK_DIR/pages" "$WORK_DIR/ocr" "$WORK_DIR/crops" "$WORK_DIR/api"
# Some native OCR builds cannot reopen files through the macOS /tmp symlink.
# Store and pass the canonical path so render, OCR, SQL, and vision all refer
# to the same physical files.
WORK_DIR=$(cd "$WORK_DIR" && pwd -P)

PSQL=(psql "$DATABASE_URL_VALUE" -X -v ON_ERROR_STOP=1)
"${PSQL[@]}" -f "$SQL_DIR/install.psql" >/dev/null

EXISTING_SHA=$("${PSQL[@]}" -At -c "SELECT source_sha256 FROM fax_stage1.documents WHERE fax_id=$FAX_ID")
if [[ -n "$EXISTING_SHA" && "$EXISTING_SHA" != "$SOURCE_SHA" ]]; then
  echo "Fax $FAX_ID already exists with a different immutable PDF checksum" >&2
  exit 73
fi

"${PSQL[@]}" -v fax_id="$FAX_ID" -v source_sha="$SOURCE_SHA" -v page_count="$PAGE_COUNT" -v source_ref="$PDF_PATH" <<'SQL' >/dev/null
INSERT INTO fax_stage1.documents (fax_id, source_sha256, source_page_count, source_reference, status)
VALUES (:'fax_id'::integer, :'source_sha', :'page_count'::integer, :'source_ref', 'ocr_loading')
ON CONFLICT (fax_id) DO UPDATE
SET status='ocr_loading', source_page_count=excluded.source_page_count, source_reference=excluded.source_reference;
DELETE FROM fax_stage1.ocr_lines WHERE fax_id=:'fax_id'::integer;
DELETE FROM fax_stage1.ocr_tokens WHERE fax_id=:'fax_id'::integer;
DELETE FROM fax_stage1.pages WHERE fax_id=:'fax_id'::integer;
SQL

find "$WORK_DIR/pages" -type f -name 'page-*.png' -delete
find "$WORK_DIR/ocr" -type f -name 'page-*.tsv' -delete
find "$WORK_DIR/crops" -type f -name 'row-*.png' -delete

pdftoppm -r 300 -png "$PDF_PATH" "$WORK_DIR/pages/page" >/dev/null 2>&1
RENDERED_COUNT=$(find "$WORK_DIR/pages" -type f -name 'page-*.png' | wc -l | tr -d ' ')
[[ "$RENDERED_COUNT" = "$PAGE_COUNT" ]] || { echo "Rendered $RENDERED_COUNT of $PAGE_COUNT pages" >&2; exit 65; }

page_number=0
while IFS= read -r page_png; do
  page_number=$((page_number + 1))
  page_key=$(printf '%03d' "$page_number")
  tsv_path="$WORK_DIR/ocr/page-$page_key.tsv"
  tesseract "$page_png" stdout --psm 6 tsv 2>/dev/null > "$tsv_path"
  "${PSQL[@]}" -c "TRUNCATE fax_stage1.ocr_import" >/dev/null
  "${PSQL[@]}" -c "\copy fax_stage1.ocr_import FROM STDIN WITH (FORMAT csv, DELIMITER E'\t', HEADER true, QUOTE E'\b')" < "$tsv_path" >/dev/null
  "${PSQL[@]}" -v fax_id="$FAX_ID" -v page_number="$page_number" -f "$SQL_DIR/load-page.psql" >/dev/null
done < <(find "$WORK_DIR/pages" -type f -name 'page-*.png' | sort -V)

"${PSQL[@]}" -v fax_id="$FAX_ID" -f "$SQL_DIR/build-lines.psql" >/dev/null
"${PSQL[@]}" -v fax_id="$FAX_ID" -f "$SQL_DIR/process.psql" >/dev/null
"${PSQL[@]}" -v fax_id="$FAX_ID" -v work_dir="$WORK_DIR" -f "$SQL_DIR/finalize.psql" >/dev/null
"${PSQL[@]}" -v fax_id="$FAX_ID" -v work_dir="$WORK_DIR" -f "$SQL_DIR/cross-fax-audit.psql" >/dev/null

while IFS='|' read -r request_id page_number crop_y crop_height crop_path; do
  [[ -n "$request_id" ]] || continue
  crop_prefix=${crop_path%.png}
  pdftoppm -f "$page_number" -l "$page_number" -r 300 \
    -x 110 -y "$crop_y" -W 2320 -H "$crop_height" -singlefile -png \
    "$PDF_PATH" "$crop_prefix" >/dev/null 2>&1
done < <("${PSQL[@]}" -At -F '|' -c "
SELECT request.request_id, candidate.source_page,
       greatest(candidate.source_top_px - 35, 0),
       least(candidate.source_bottom_px, page.height_px) - greatest(candidate.source_top_px - 35, 0) + 35,
       request.crop_path
FROM fax_stage1.vision_requests AS request
JOIN fax_stage1.candidate_rows AS candidate USING (candidate_row_id)
JOIN fax_stage1.pages AS page ON page.fax_id=candidate.fax_id AND page.page_number=candidate.source_page
WHERE request.fax_id=$FAX_ID AND request.request_status='pending'
ORDER BY request.request_id")

PENDING=$("${PSQL[@]}" -At -c "SELECT count(*) FROM fax_stage1.vision_requests WHERE fax_id=$FAX_ID AND request_status='pending'")

if [[ "$PENDING" -gt 0 && "$SKIP_VISION" = false && -n "${OPENAI_API_KEY:-}" ]]; then
  MODEL=${FAX_STAGE1_VISION_MODEL:-gpt-6-astra}
  PROMPT=$(<"$SQL_DIR/vision-prompt.txt")
  while IFS='|' read -r request_id crop_path requested_fields; do
    [[ -f "$crop_path" ]] || continue
    image_data=$(base64 < "$crop_path" | tr -d '\n')
    body_path="$WORK_DIR/api/request-$request_id.json"
    response_path="$WORK_DIR/api/response-$request_id.json"
    jq -n \
      --arg model "$MODEL" \
      --arg prompt "$PROMPT Requested fields: $requested_fields" \
      --arg image "data:image/png;base64,$image_data" \
      --slurpfile schema "$SQL_DIR/vision-schema.json" \
      '{model:$model,store:false,input:[{role:"user",content:[{type:"input_text",text:$prompt},{type:"input_image",image_url:$image,detail:"original"}]}],text:{format:{type:"json_schema",name:"fax_stage1_row",strict:true,schema:$schema[0]}}}' \
      > "$body_path"
    if curl --fail --silent --show-error --retry 2 \
      https://api.openai.com/v1/responses \
      -H "Authorization: Bearer $OPENAI_API_KEY" \
      -H 'Content-Type: application/json' \
      --data-binary "@$body_path" > "$response_path"; then
      structured=$(jq -er '[.output[]?.content[]? | select(.type=="output_text") | .text] | join("") | fromjson' "$response_path") || continue
      jq -nr --arg id "$request_id" --argjson raw "$structured" '[$id,$raw] | @csv' | \
        "${PSQL[@]}" -c "\copy fax_stage1.vision_response_import(request_id,raw_result) FROM STDIN WITH (FORMAT csv)" >/dev/null
    fi
  done < <("${PSQL[@]}" -At -F '|' -c "SELECT request_id,crop_path,array_to_string(requested_fields,',') FROM fax_stage1.vision_requests WHERE fax_id=$FAX_ID AND request_status='pending' ORDER BY request_id")
  "${PSQL[@]}" -v fax_id="$FAX_ID" -f "$SQL_DIR/apply-vision.psql" >/dev/null
elif [[ "$PENDING" -gt 0 ]]; then
  "${PSQL[@]}" -c "UPDATE fax_stage1.documents SET status='stage1_waiting_for_vision' WHERE fax_id=$FAX_ID" >/dev/null
else
  "${PSQL[@]}" -c "
UPDATE fax_stage1.documents
SET status = CASE
  WHEN EXISTS (
    SELECT 1 FROM fax_stage1.resolved_rows
    WHERE fax_id=$FAX_ID AND resolution_status='unresolved'
  ) THEN 'stage1_complete_with_unresolved'
  ELSE 'stage1_complete_pre_card_match'
END
WHERE fax_id=$FAX_ID" >/dev/null
fi

"${PSQL[@]}" -P pager=off -c "
SELECT document.fax_id, document.status, document.source_page_count AS pages,
       count(row.*) AS rows,
       count(*) FILTER (WHERE row.resolution_status='resolved') AS resolved,
       count(*) FILTER (WHERE row.resolution_status='unresolved') AS unresolved
FROM fax_stage1.documents AS document
LEFT JOIN fax_stage1.resolved_rows AS row ON row.fax_id=document.fax_id
WHERE document.fax_id=$FAX_ID
GROUP BY document.fax_id,document.status,document.source_page_count;"
