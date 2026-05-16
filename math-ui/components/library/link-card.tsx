import Link from "next/link";
import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Clickable card — hover-styled wrapper around a Link. The body is
 * arbitrary; the whole surface is the link target. Pass `chevron={false}`
 * to suppress the trailing affordance for very dense rows.
 */
export function LinkCard({
  href,
  children,
  chevron = true,
  contentClassName,
}: {
  href: string;
  children: ReactNode;
  chevron?: boolean;
  contentClassName?: string;
}) {
  return (
    <Link href={href} className="group block">
      <Card className="ring-foreground/8 transition-all duration-150 group-hover:ring-foreground/15 group-hover:shadow-sm">
        <CardContent
          className={cn(
            "flex items-center gap-3 px-4 py-3.5",
            contentClassName
          )}
        >
          <div className="min-w-0 flex-1">{children}</div>
          {chevron && (
            <ChevronRight className="size-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
          )}
        </CardContent>
      </Card>
    </Link>
  );
}
