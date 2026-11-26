# Failures

_I record real failures as they happen. Evidence: the `runs.jsonl` line (`status: "error"`), the
kernel log in `outputs/logs/`, or the command output. How the pipeline handles each class of failure is in ARCHITECTURE.md →
Failure handling._

Format for each entry:

```
## F<n>: <symptom in one line>          date · stage · run_id / call_id
What happened: <error text, what I saw>
Cause:         <root cause, once known>
Fix:           <what I changed: code, config, prompt, or "switched to Ken Burns">
Prevention:    <test, check or retry rule added so it can't recur silently>
```

## Log

_(my entries here)_
