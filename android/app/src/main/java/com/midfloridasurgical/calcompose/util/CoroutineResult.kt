package com.midfloridasurgical.calcompose.util

import kotlin.coroutines.cancellation.CancellationException

private const val COMPOSITION_LEFT_MESSAGE = "The coroutine scope left the composition"

/** True for structured-concurrency / composition-leave cancels that must not surface as UI errors. */
fun Throwable.isBenignCancel(): Boolean =
    this is CancellationException ||
        this is java.util.concurrent.CancellationException ||
        message == COMPOSITION_LEFT_MESSAGE

/**
 * Like [Result.onFailure], but never treats cancel as an error.
 * Ignores benign cancels (Compose leaves composition via [CancellationException]).
 */
inline fun <T> Result<T>.onFailureUnlessCancelled(
    action: (Throwable) -> Unit,
): Result<T> {
    val error = exceptionOrNull() ?: return this
    if (error.isBenignCancel()) return this
    action(error)
    return this
}
