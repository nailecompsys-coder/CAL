package com.midfloridasurgical.calcompose.data.models

import kotlinx.serialization.Serializable

enum class SessionRole(val storedValue: String) {
    SURGEON("surgeon"),
    SCHEDULER("scheduler");

    companion object {
        fun fromStoredValue(value: String?): SessionRole =
            entries.firstOrNull { it.storedValue == value } ?: SURGEON
    }
}

@Serializable
data class OtpRequest(val email: String)

@Serializable
data class OtpVerifyRequest(val email: String, val code: String)

@Serializable
data class OtpRequestResponse(
    val ok: Boolean? = null,
    val message: String? = null,
    val sent: Boolean? = null,
    val roles: List<String>? = null,
    val devCode: String? = null,
)

/** Unified native OTP verify — mirrors iOS `NativeUnifiedOtpVerifyResponse`. */
@Serializable
data class OtpVerifyResponse(
    val token: String,
    val role: String = "surgeon",
    val roles: List<String> = emptyList(),
    val tokens: OtpVerifyTokens = OtpVerifyTokens(),
)

@Serializable
data class OtpVerifyTokens(
    val surgeon: String? = null,
    val scheduler: String? = null,
)
