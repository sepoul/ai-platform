/**
 * `PlatformSession` — TypeScript mirror of the Python
 * `ai_platform.session.PlatformSession`. One object per process /
 * browser tab, owning the API client connection.
 *
 *     const session = new PlatformSession({ apiUrl: "http://platform:8000" });
 *     const handle = await session.submitJob("math_qa", { question_text: "..." });
 *     const result = await (await handle.wait({ timeoutMs: 60_000 })).result();
 *
 * The browser-side path goes through the BFF proxy (`/api/...` on the
 * UI's own origin). Construct with `apiUrl: "/api"` in that case.
 * Server-side code (Next.js route handlers) constructs with the
 * upstream URL directly.
 */
import { createApiClient, type ApiClient } from "./client";
import {
  type Artifact,
  type ArtifactListResponse,
  type FullArtifactListResponse,
  type ArtifactTypeListResponse,
  type ArtifactTypeRecord,
  type CodePackageRecord,
  type JobDefinitionRecord,
  type JobResultResponse,
  type JobStatusResponse,
  type RunSubmitResponse,
  type UserComment,
  type WorkflowListResponse,
  type WorkflowSpecResponse,
  TERMINAL_STATUSES,
} from "./types";

export class PlatformSessionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PlatformSessionError";
  }
}

export class JobNotFoundError extends PlatformSessionError {
  constructor(message: string) {
    super(message);
    this.name = "JobNotFoundError";
  }
}

export class JobTimeoutError extends PlatformSessionError {
  constructor(message: string) {
    super(message);
    this.name = "JobTimeoutError";
  }
}

export interface PlatformSessionOptions {
  apiUrl: string;
}

/** Filter + pagination options shared by the artifact list reads. */
export interface ListArtifactsOpts {
  jobId?: string;
  artifactType?: string;
  limit?: number;
  offset?: number;
  /** Equality filters on whitelisted top-level domain fields (PR-3b),
   * e.g. `{ source_note_id: "<id>" }`. A non-whitelisted field 400s. */
  fields?: Record<string, string | number | boolean>;
}

/** Build the `/artifacts` query object from {@link ListArtifactsOpts}.
 * Domain `fields` are spread in as bare query params (the backend reads
 * any non-reserved key as a field filter). */
function artifactQuery(opts: ListArtifactsOpts): Record<string, string | number | boolean> {
  const query: Record<string, string | number | boolean> = {};
  if (opts.jobId) query.job_id = opts.jobId;
  if (opts.artifactType) query.artifact_type = opts.artifactType;
  if (opts.limit) query.limit = opts.limit;
  if (opts.offset) query.offset = opts.offset;
  for (const [key, value] of Object.entries(opts.fields ?? {})) {
    if (value !== undefined) query[key] = value;
  }
  return query;
}

const TERMINAL_SET = new Set<string>(TERMINAL_STATUSES);

export class PlatformSession {
  private readonly client: ApiClient;

  constructor(opts: PlatformSessionOptions) {
    this.client = createApiClient(opts.apiUrl);
  }

  // ---- Catalog reads ----

  async listJobDefinitions(opts: { runtimeSelector?: string } = {}): Promise<JobDefinitionRecord[]> {
    const { data, error } = await this.client.GET("/job-definitions", {
      params: { query: opts.runtimeSelector ? { runtime_selector: opts.runtimeSelector } : {} },
    });
    if (error) throw new PlatformSessionError(`/job-definitions failed: ${JSON.stringify(error)}`);
    return data ?? [];
  }

  async getJobDefinition(name: string): Promise<JobDefinitionRecord> {
    const { data, error, response } = await this.client.GET(
      "/job-definitions/by-name/{name}",
      { params: { path: { name } } },
    );
    if (response.status === 404) throw new JobNotFoundError(`No JobDefinition named ${name}`);
    if (error) throw new PlatformSessionError(`/job-definitions/by-name/${name} failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError(`/job-definitions/by-name/${name} returned empty body`);
    return data;
  }

  /**
   * Fetch a specific versioned JobDefinition by its catalog id
   * (`"{name}@{version}"`). Distinct from `getJobDefinition(name)` —
   * that one returns the latest version per name; this one pins.
   */
  async getJobDefinitionById(definitionId: string): Promise<JobDefinitionRecord> {
    const { data, error, response } = await this.client.GET(
      "/job-definitions/{definition_id}",
      { params: { path: { definition_id: definitionId } } },
    );
    if (response.status === 404) throw new JobNotFoundError(`JobDefinition not found: ${definitionId}`);
    if (error) throw new PlatformSessionError(`/job-definitions/${definitionId} failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError(`/job-definitions/${definitionId} returned empty body`);
    return data;
  }

  async listArtifactTypes(opts: { domain?: string } = {}): Promise<ArtifactTypeRecord[]> {
    const { data, error } = await this.client.GET("/artifact-types", {
      params: { query: opts.domain ? { domain: opts.domain } : {} },
    });
    if (error) throw new PlatformSessionError(`/artifact-types failed: ${JSON.stringify(error)}`);
    return data ?? [];
  }

  async listCodePackages(opts: { runtimeSelector?: string } = {}): Promise<CodePackageRecord[]> {
    const { data, error } = await this.client.GET("/code-packages", {
      params: { query: opts.runtimeSelector ? { runtime_selector: opts.runtimeSelector } : {} },
    });
    if (error) throw new PlatformSessionError(`/code-packages failed: ${JSON.stringify(error)}`);
    return data ?? [];
  }

  // ---- Job lifecycle ----

  async submitJob(jobType: string, payload: Record<string, unknown>): Promise<JobHandle> {
    const body = { job_type: jobType, ...payload };
    // The openapi-fetch path validates against the discriminated union
    // dynamically. Cast through `unknown` to satisfy strict mode.
    const { data, error } = await this.client.POST(
      "/jobs/runs/submit",
      { body: body as never },
    );
    if (error) throw new PlatformSessionError(`/jobs/runs/submit failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError("/jobs/runs/submit returned empty body");
    return new JobHandle(this, data.job_id, jobType);
  }

  async getJob(jobId: string): Promise<JobHandle> {
    const status = await this.fetchJobStatus(jobId);
    return new JobHandle(this, status.job_id, status.job_type, status);
  }

  async listJobs(opts: { status?: string; jobType?: string; limit?: number } = {}): Promise<JobStatusResponse[]> {
    const query: Record<string, string | number> = {};
    if (opts.status) query.status = opts.status;
    if (opts.jobType) query.job_type = opts.jobType;
    if (opts.limit) query.limit = opts.limit;
    const { data, error } = await this.client.GET("/jobs", {
      params: { query: query as never },
    });
    if (error) throw new PlatformSessionError(`/jobs failed: ${JSON.stringify(error)}`);
    return data ?? [];
  }

  /**
   * Post a reviewer's verdict (approve / reject / comment) to a job
   * waiting at a human-review gate. The job transitions out of
   * WAITING_INPUT into RUNNING (then SUCCEEDED / FAILED) after this.
   */
  async submitReview(jobId: string, review: UserComment): Promise<RunSubmitResponse> {
    const { data, error, response } = await this.client.POST(
      "/jobs/{job_id}/review",
      {
        params: { path: { job_id: jobId } },
        body: review as never,
      },
    );
    if (response.status === 404) throw new JobNotFoundError(`Job not found: ${jobId}`);
    if (error) throw new PlatformSessionError(`/jobs/${jobId}/review failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError(`/jobs/${jobId}/review returned empty body`);
    return data;
  }

  // ---- Artifacts (registry surface; coexists with /artifact-types) ----

  /**
   * Summary list (cheap default). Filters compile to one backend query:
   * `jobId`/`artifactType` envelope filters, `limit`/`offset` pagination
   * (PR-3c), and `fields` — equality filters on whitelisted domain fields,
   * e.g. `{ source_note_id }` (PR-3b). A non-whitelisted field 400s.
   */
  async listArtifacts(opts: ListArtifactsOpts = {}): Promise<ArtifactListResponse> {
    const { data, error } = await this.client.GET("/artifacts", {
      params: { query: artifactQuery(opts) as never },
    });
    if (error) throw new PlatformSessionError(`/artifacts failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError("/artifacts returned empty body");
    // The 200 schema is a union (summary | full); this path never sends
    // `full`, so the backend always returns the summary shape.
    return data as ArtifactListResponse;
  }

  /**
   * Full-projection list (PR-3a `full=true`) — full typed artifacts inline
   * (`concepts`/`latex`/`text`, `storage_url` hydrated), so one request
   * hydrates a whole page instead of a `getArtifact` per row. Same filter
   * options as {@link listArtifacts}.
   */
  async listArtifactsFull(opts: ListArtifactsOpts = {}): Promise<FullArtifactListResponse> {
    const { data, error } = await this.client.GET("/artifacts", {
      params: { query: { ...artifactQuery(opts), full: true } as never },
    });
    if (error) throw new PlatformSessionError(`/artifacts?full failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError("/artifacts returned empty body");
    return data as FullArtifactListResponse;
  }

  /**
   * Batch-hydrate artifacts by id in one round-trip (PR-3d) — kills the
   * per-id `getArtifact` fan-out when reading `result.artifact_refs` or a
   * SeedStep set. Fail-loud: any missing id 404s the whole batch.
   */
  async batchGetArtifacts(ids: string[]): Promise<Artifact[]> {
    const { data, error } = await this.client.POST("/artifacts/batch", {
      body: { ids } as never,
    });
    if (error) throw new PlatformSessionError(`/artifacts/batch failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError("/artifacts/batch returned empty body");
    return data as Artifact[];
  }

  async getArtifact(artifactId: string): Promise<Artifact> {
    const { data, error, response } = await this.client.GET(
      "/artifacts/{artifact_id}",
      { params: { path: { artifact_id: artifactId } } },
    );
    if (response.status === 404) {
      throw new PlatformSessionError(`Artifact not found: ${artifactId}`);
    }
    if (error) throw new PlatformSessionError(`/artifacts/${artifactId} failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError(`/artifacts/${artifactId} returned empty body`);
    return data as Artifact;
  }

  /** Older artifact-types registry endpoint (`/artifacts/types`). */
  async listArtifactTypesRegistry(): Promise<ArtifactTypeListResponse> {
    const { data, error } = await this.client.GET("/artifacts/types", {});
    if (error) throw new PlatformSessionError(`/artifacts/types failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError("/artifacts/types returned empty body");
    return data;
  }

  // ---- Workflows ----

  async listWorkflows(): Promise<WorkflowListResponse> {
    const { data, error } = await this.client.GET("/workflows", {});
    if (error) throw new PlatformSessionError(`/workflows failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError("/workflows returned empty body");
    return data;
  }

  async getWorkflowSpec(jobType: string): Promise<WorkflowSpecResponse> {
    const { data, error, response } = await this.client.GET(
      "/workflows/{job_type}",
      { params: { path: { job_type: jobType } } },
    );
    if (response.status === 404) {
      throw new PlatformSessionError(`Workflow not found for job type: ${jobType}`);
    }
    if (error) throw new PlatformSessionError(`/workflows/${jobType} failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError(`/workflows/${jobType} returned empty body`);
    return data;
  }

  // ---- Internal — called by JobHandle ----

  async fetchJobStatus(jobId: string): Promise<JobStatusResponse> {
    const { data, error, response } = await this.client.GET(
      "/jobs/{job_id}",
      { params: { path: { job_id: jobId } } },
    );
    if (response.status === 404) throw new JobNotFoundError(`Job not found: ${jobId}`);
    if (error) throw new PlatformSessionError(`/jobs/${jobId} failed: ${JSON.stringify(error)}`);
    if (!data) throw new PlatformSessionError(`/jobs/${jobId} returned empty body`);
    return data;
  }

  async fetchJobResult(jobId: string): Promise<JobResultResponse | null> {
    const { data, error, response } = await this.client.GET(
      "/jobs/{job_id}/result",
      { params: { path: { job_id: jobId } } },
    );
    if (response.status === 409) return null; // Not in a result-fetchable status.
    if (response.status === 404) throw new JobNotFoundError(`Job not found: ${jobId}`);
    if (error) throw new PlatformSessionError(`/jobs/${jobId}/result failed: ${JSON.stringify(error)}`);
    return data ?? null;
  }
}

/**
 * Lazy pointer to a running / completed job. Doesn't auto-poll —
 * callers do `await handle.refresh()` or `await handle.wait({...})`.
 */
export class JobHandle {
  public readonly jobId: string;
  public readonly jobType: string;
  private statusCache: JobStatusResponse | null;

  constructor(
    private readonly session: PlatformSession,
    jobId: string,
    jobType: string,
    statusCache: JobStatusResponse | null = null,
  ) {
    this.jobId = jobId;
    this.jobType = jobType;
    this.statusCache = statusCache;
  }

  async refresh(): Promise<this> {
    this.statusCache = await this.session.fetchJobStatus(this.jobId);
    return this;
  }

  async status(): Promise<string> {
    if (this.statusCache === null) await this.refresh();
    return this.statusCache!.status;
  }

  async isDone(): Promise<boolean> {
    return TERMINAL_SET.has(await this.status());
  }

  /**
   * Returns the last-fetched status row in full (or null if never
   * refreshed and never seeded). Synchronous — call `refresh()` first
   * if you want the latest.
   */
  statusPayload(): JobStatusResponse | null {
    return this.statusCache;
  }

  async wait(opts: { timeoutMs?: number; pollIntervalMs?: number } = {}): Promise<this> {
    const timeoutMs = opts.timeoutMs ?? 60_000;
    const pollIntervalMs = opts.pollIntervalMs ?? 1_000;
    const deadline = Date.now() + timeoutMs;
    while (true) {
      await this.refresh();
      if (await this.isDone()) return this;
      if (Date.now() >= deadline) {
        throw new JobTimeoutError(
          `Job ${this.jobId} did not reach terminal state in ${timeoutMs}ms ` +
            `(last status: ${await this.status()})`,
        );
      }
      await new Promise((r) => setTimeout(r, pollIntervalMs));
    }
  }

  async result(opts: { timeoutMs?: number; pollIntervalMs?: number } = {}): Promise<JobResultResponse> {
    await this.wait(opts);
    const s = await this.status();
    if (s !== "SUCCEEDED" && s !== "WAITING_INPUT") {
      const err = this.statusCache?.error_message ?? "";
      throw new PlatformSessionError(`Job ${this.jobId} ended in ${s}: ${err}`);
    }
    const r = await this.session.fetchJobResult(this.jobId);
    if (r === null) {
      throw new PlatformSessionError(
        `Job ${this.jobId} status ${s} but result endpoint returned 409`,
      );
    }
    return r;
  }
}
