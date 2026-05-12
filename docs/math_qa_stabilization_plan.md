# Math Q&A artifact stabilization — landing plan

Spec lives in [FEATURES.md](../FEATURES.md) ("Math Q&A artifact
stabilization"). This is the order of work.

**Status:** sidestepped step 1's full set; landed a narrower
LaTeX-aware shape via `LatexAnswerArtifact` + `GenerateLatexStep`
(see [NEXT_BEST_STEPS §1g/§1i](../NEXT_BEST_STEPS.md)) which covers
the LaTeX-correctness story without committing to the
`RichContentArtifact` model yet. Steps 1–4 below remain the path
forward when we want concepts / references / exercises as
first-class.

1. **Add the new artifact types first.** `ConceptArtifact`,
   `RichContentArtifact`, `ReferenceArtifact`, `ExerciseArtifact`,
   `ApplicationArtifact`, `ConceptRelationArtifact`,
   `MathAnswerArtifact`. Pure pydantic models; register them in the
   math QA artifact registry. No workflow changes yet — tests just
   roundtrip them through the artifact store.

2. **Replace `GeneratedAnswerArtifact` with `MathAnswerArtifact`** in
   the existing graph. Smallest-possible LaTeX-aware change. Updates
   `MathQAResult`, the persist callback, the UI types. Ships a working
   narrower version end-to-end.

3. **Build `IdentifyConceptsStep` in isolation.** Seed 10–20
   `ConceptArtifact`s by hand. Wire the LLM call that maps NL → existing
   concept by name/alias, with a mint-new fallback. Insert between
   `ReceiveQuestionStep` and the answer step. This is the bottleneck —
   get it right before fan-out.

4. **Fan-out one branch at a time.** Start with `GatherReferencesStep`
   (smallest, cache-friendly, no graph traversal needed). Then
   `ResolvePrerequisitesStep` once a few `ConceptRelationArtifact`s
   exist. Exercises / applications / next-steps / neighborhood follow
   the same shape — each its own PR + UI surface.
