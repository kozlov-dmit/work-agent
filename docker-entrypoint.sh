#!/usr/bin/env bash
set -e

# Reinstall anything the agent provisioned for itself in a previous run.
# The manifest lives in the (volume-mounted) /workspace/.work-agent directory,
# so self-installed tools survive container recreation.
work-agent bootstrap || true

exec work-agent "$@"
