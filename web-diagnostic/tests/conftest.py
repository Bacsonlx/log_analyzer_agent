"""Ensure Claude is skipped before `server` is imported (defines `runner`)."""
import os

os.environ["WEB_DIAGNOSTIC_SKIP_CLAUDE"] = "1"
