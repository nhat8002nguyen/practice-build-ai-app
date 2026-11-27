export const toMessage = (error: unknown): string =>
  error instanceof Error ? error.message : "Something went wrong";
