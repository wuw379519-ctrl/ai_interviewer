/**
 * Local stand-in for the npm `server-only` package.
 *
 * Conflict note: R3 requires `import "server-only"`, but this ticket forbids new
 * npm dependencies and the package is not in the lockfile. Mapped via tsconfig
 * paths and Next webpack alias — do not publish secrets through client bundles.
 */
if (typeof window !== "undefined") {
  throw new Error("This module cannot be imported from a Client Component.");
}

export {};
