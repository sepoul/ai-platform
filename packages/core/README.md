# aiplatform-core

Shared platform tier for [ai-platform](https://github.com/sepoul/ai-platform):
the `JobRecord` boundary, storage + compute backends, job types, artifact
contracts, and the cross-domain workspace facade. **No web framework, no AI
engine** — domains build their control-plane packages against this.

Ships the `aiplatform` CLI (`aiplatform deploy`, `declare-artifacts`,
`snapshot-openapi`).

```bash
pip install aiplatform-core
```

```python
from ai_platform.jobs.artifact import BaseArtifact
```

MIT licensed. See the [repo](https://github.com/sepoul/ai-platform) for docs.
