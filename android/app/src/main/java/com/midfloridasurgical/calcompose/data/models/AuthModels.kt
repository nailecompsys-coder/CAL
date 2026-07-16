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
    val message: String? = null,
    val sent: Boolean? = null,
)

@Serializable
data class OtpVerifyResponse(val token: String)
