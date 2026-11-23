"use client";

import { Button } from "@/components/ui/button";

export default function ErrorBoundary({ reset }: { reset: () => void }) {
  return <div className="panel empty" role="alert"><h1>Something interrupted this page</h1><Button onClick={reset}>Try again</Button></div>;
}
