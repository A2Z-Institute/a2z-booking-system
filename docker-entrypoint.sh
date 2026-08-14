#!/bin/sh
set -eu

database_file="${A2Z_DATABASE:-/data/a2z_booking.db}"
database_directory="$(dirname "$database_file")"

mkdir -p "$database_directory"
chown a2z:a2z "$database_directory"

if [ -e "$database_file" ]; then
    chown a2z:a2z "$database_file"
fi

exec gosu a2z "$@"
