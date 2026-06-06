from __future__ import annotations

MAGIC_LINK_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#f5f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        color:#1c1c1e;padding:32px 16px}}
  .wrap{{max-width:520px;margin:0 auto;background:#fff;border-radius:16px;
         overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)}}
  .header{{background:#1a2540;padding:28px 32px;text-align:center}}
  .header h1{{color:#fff;font-size:20px;font-weight:700;margin-bottom:4px}}
  .header p{{color:#94a3b8;font-size:13px}}
  .body{{padding:32px}}
  .greeting{{font-size:17px;font-weight:600;margin-bottom:12px}}
  .copy{{font-size:14px;color:#475569;line-height:1.6;margin-bottom:24px}}
  .btn{{display:block;background:#007aff;color:#fff;text-decoration:none;
        font-size:16px;font-weight:700;text-align:center;padding:15px 24px;
        border-radius:12px;margin-bottom:28px}}
  .divider{{display:flex;align-items:center;gap:12px;color:#94a3b8;
            font-size:12px;margin-bottom:24px}}
  .divider::before,.divider::after{{content:'';flex:1;height:1px;background:#e2e8f0}}
  .qr-wrap{{text-align:center;margin-bottom:24px}}
  .qr-wrap img{{width:180px;height:180px;border:1px solid #e2e8f0;border-radius:12px;padding:8px}}
  .qr-label{{font-size:12px;color:#94a3b8;margin-top:8px}}
  .link-box{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
             padding:10px 14px;font-size:11px;color:#64748b;word-break:break-all;
             margin-bottom:24px}}
  .expiry{{font-size:12px;color:#94a3b8;margin-bottom:20px}}
  .footer{{background:#f8fafc;border-top:1px solid #e2e8f0;padding:18px 32px;
           font-size:11px;color:#94a3b8;text-align:center;line-height:1.6}}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <h1>{app_name}</h1>
    <p>Mid Florida Surgical</p>
  </div>
  <div class="body">
    <div class="greeting">Hi {to_name} 👋</div>
    <p class="copy">
      Your access link is ready. Tap the button below on your phone to register
      this device — or scan the QR code if you're reading this on a desktop.
    </p>

    <!-- Big tap button -->
    <a href="{magic_url}" class="btn">Open {app_name} →</a>

    <!-- QR code for desktop readers -->
    <div class="divider">or scan with your phone camera</div>
    <div class="qr-wrap">
      <img src="cid:qrcode" alt="QR code">
      <div class="qr-label">Point your phone camera here</div>
    </div>

    <!-- Raw link fallback -->
    <p class="copy" style="font-size:12px;margin-bottom:8px">
      Can't tap or scan? Copy this link into your phone's browser:
    </p>
    <div class="link-box">{magic_url}</div>

    <p class="expiry">⏱ This link expires in {expiry_hours} hours and can only be used once.</p>
  </div>
  <div class="footer">
    Mid Florida Surgical · This email was sent by {app_name}<br>
    If you didn't expect this, you can safely ignore it.
  </div>
</div>
</body>
</html>
"""

MAGIC_LINK_TEXT = """\
Hi {to_name},

Your {app_name} access link:

  {magic_url}

Open this link on your phone to register your device.
It expires in {expiry_hours} hours and can only be used once.

If you didn't expect this, you can safely ignore it.
— Mid Florida Surgical
"""
