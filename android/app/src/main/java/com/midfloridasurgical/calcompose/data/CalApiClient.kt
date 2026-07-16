package com.midfloridasurgical.calcompose.data

import com.midfloridasurgical.calcompose.BuildConfig
import com.midfloridasurgical.calcompose.data.models.CallCoverageRequest
import com.midfloridasurgical.calcompose.data.models.NativeCallCoverageResponse
import com.midfloridasurgical.calcompose.data.models.NativeHomeResponse
import com.midfloridasurgical.calcompose.data.models.NativePatientScheduleResponse
import com.midfloridasurgical.calcompose.data.models.NativeRequestOffResponse
import com.midfloridasurgical.calcompose.data.models.OtpRequest
import com.midfloridasurgical.calcompose.data.models.OtpRequestResponse
import com.midfloridasurgical.calcompose.data.models.OtpVerifyRequest
import com.midfloridasurgical.calcompose.data.models.OtpVerifyResponse
import com.midfloridasurgical.calcompose.data.models.TimeOffSubmitRequest
import com.midfloridasurgical.calcompose.data.models.TimeOffSubmitSegment
import java.io.IOException
import java.time.LocalDate
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

class CalApiClient(
    private val baseUrl: String = if (BuildConfig.DEBUG) {
        "http://10.0.2.2:3005"
    } else {
        "https://cal.midfloridasurgical.com"
    },
    private val httpClient: OkHttpClient = OkHttpClient(),
    private val json: Json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = true
    },
) {
    suspend fun requestOtp(email: String): OtpRequestResponse = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$baseUrl/api/surgeon/otp/request")
            .post(json.encodeToString(OtpRequest(email)).jsonBody())
            .build()
        json.decodeFromString(execute(request))
    }

    suspend fun verifyOtp(email: String, code: String): OtpVerifyResponse =
        withContext(Dispatchers.IO) {
            val request = Request.Builder()
                .url("$baseUrl/api/surgeon/otp/verify")
                .post(json.encodeToString(OtpVerifyRequest(email, code)).jsonBody())
                .build()
            json.decodeFromString(execute(request))
        }

    suspend fun fetchHome(
        token: String,
        deviceToken: String,
        start: LocalDate = LocalDate.now(),
        end: LocalDate = start.plusDays(60),
    ): NativeHomeResponse = withContext(Dispatchers.IO) {
        val request = authenticatedGet(
            path = "/api/native/home?start=$start&end=$end",
            token = token,
            deviceToken = deviceToken,
        )
        json.decodeFromString(execute(request))
    }

    suspend fun fetchPatientSchedule(
        token: String,
        deviceToken: String,
        start: LocalDate,
        end: LocalDate,
    ): NativePatientScheduleResponse = withContext(Dispatchers.IO) {
        val request = authenticatedGet(
            path = "/api/native/patient-schedule?start=$start&end=$end",
            token = token,
            deviceToken = deviceToken,
        )
        json.decodeFromString(execute(request))
    }

    suspend fun submitRequestOff(
        token: String,
        deviceToken: String,
        startDate: LocalDate,
        endDate: LocalDate,
        reason: String,
        notes: String = "",
    ): NativeRequestOffResponse = withContext(Dispatchers.IO) {
        val segments = buildList {
            var cursor = startDate
            while (!cursor.isAfter(endDate)) {
                add(
                    TimeOffSubmitSegment(
                        date = cursor.toString(),
                        isFullDay = true,
                        start = "07:00",
                        end = "17:00",
                    ),
                )
                cursor = cursor.plusDays(1)
            }
        }
        val payload = TimeOffSubmitRequest(
            startDate = startDate.toString(),
            endDate = endDate.toString(),
            reason = reason,
            notes = notes,
            isFullDay = true,
            segments = segments,
        )
        val request = Request.Builder()
            .url("$baseUrl/api/native/request-off")
            .header("Authorization", "Bearer $token")
            .header("X-CAL-Device-Token", deviceToken)
            .post(json.encodeToString(payload).jsonBody())
            .build()
        val response = json.decodeFromString<NativeRequestOffResponse>(execute(request))
        if (!response.ok) {
            throw CalApiException(
                statusCode = 400,
                message = response.warnings.joinToString(" ").ifBlank {
                    "Request was not submitted."
                },
            )
        }
        response
    }

    suspend fun submitCallCoverage(
        token: String,
        deviceToken: String,
        rotationId: Int,
        coveringSurgeonId: Int,
        notes: String = "",
    ): NativeCallCoverageResponse = withContext(Dispatchers.IO) {
        val payload = CallCoverageRequest(
            rotationId = rotationId,
            coveringSurgeonId = coveringSurgeonId,
            notes = notes,
        )
        val request = Request.Builder()
            .url("$baseUrl/api/native/call-coverage")
            .header("Authorization", "Bearer $token")
            .header("X-CAL-Device-Token", deviceToken)
            .post(json.encodeToString(payload).jsonBody())
            .build()
        json.decodeFromString(execute(request))
    }

    private fun authenticatedGet(path: String, token: String, deviceToken: String): Request =
        Request.Builder()
            .url("$baseUrl$path")
            .header("Authorization", "Bearer $token")
            .header("X-CAL-Device-Token", deviceToken)
            .header("Accept", JSON_MEDIA_TYPE.toString())
            .get()
            .build()

    private fun execute(request: Request): String {
        httpClient.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val readableMessage = runCatching {
                    val payload = JSONObject(body)
                    payload.optString("detail").ifBlank { payload.optString("message") }
                }.getOrNull()
                throw CalApiException(
                    statusCode = response.code,
                    message = readableMessage?.takeIf { it.isNotBlank() }
                        ?: "CAL request failed (${response.code}).",
                )
            }
            return body
        }
    }

    private fun String.jsonBody() = toRequestBody(JSON_MEDIA_TYPE)

    private companion object {
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}

class CalApiException(
    val statusCode: Int,
    override val message: String,
) : IOException(message)
