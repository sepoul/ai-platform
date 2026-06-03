"""PlatformSession — the Spark-session-style runtime entry point.

A single object per process that owns the API connection and gives a
domain or downstream caller one place to:

- Browse the catalogs (JobDefinitions, ArtifactTypes, CodePackages).
- Submit a job and get back a `JobHandle` whose lifecycle methods are
  poll-based on the same connection.
- List / get / refresh existing jobs.

```python
from ai_platform.session import PlatformSession

session = PlatformSession.connect("http://my-platform:8000")
handle = session.submit_job("math_qa", {"question": "what is 2+2?"})
result = handle.wait(timeout=120).result()
```

Where `aiplatform deploy` is the build-time half (push definitions),
`PlatformSession` is the run-time half (drive the platform from
notebook / script / friend's domain code).

Today: dict-in, dict-out at the JSON boundary. A future enhancement
can hand back typed pydantic models built from the JobDefinition's
`result_schema`, but no caller has needed that yet.
"""
from ai_platform.session.session import JobHandle, PlatformSession

__all__ = ["PlatformSession", "JobHandle"]
