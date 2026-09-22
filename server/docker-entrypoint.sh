#!/bin/sh
set -eu

mkdir -p /var/lib/cal/faxes
chown appuser:appuser /var/lib/cal/faxes

exec gosu appuser "$@"
