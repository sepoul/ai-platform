/**
 * App-level component library — composable building blocks layered on
 * top of `components/ui/` (shadcn primitives). New routes/components
 * should reach for these before rolling bespoke loading cards, page
 * headers, etc.
 */
export { PageContainer } from "./page-container";
export { PageHeader } from "./page-header";
export { Section } from "./section";
export { LoadingCard, ErrorCard, EmptyCard } from "./status-card";
export { LinkCard } from "./link-card";
export { FieldList, FieldBadge, type FieldRow } from "./field-list";
export { Markdown } from "./markdown";
export { Latex } from "./latex";
export { Figure } from "./figure";
export type {
  FigureSpec,
  FigureElement,
  BlobElement,
  RectElement,
  CircleElement,
  ArrowElement,
  LineElement,
  LabelElement,
  PolygonElement,
  DotElement,
} from "./figure";
