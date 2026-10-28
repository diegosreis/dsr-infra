# Native error_log cannot interpolate a sanitized URI. Suppress context,
# not the event, whenever a diagnostic can contain a secret-bearing URL.
# Percent-encoded context is intentionally fail-closed; queries too.
{
    lower = tolower($0)
    if (lower ~ /\/convite\// || lower ~ /\/api\/v1\/public\/patient-intake\// || index($0, "%") || index($0, "?")) {
        print "[nginx] diagnostic context [redacted] (sensitive/encoded URI or query)"
    } else {
        print $0
    }
    fflush()
}
