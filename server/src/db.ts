import { Pool } from "pg";
import dotenv from "dotenv";

// Load .env and allow it to override any existing environment variables in this process.
// This is useful in dev when the shell or editor has placeholder env entries like '${env:DATABASE_URL}'.
dotenv.config({ override: true });

const connectionString = process.env.DATABASE_URL;
const nodeEnv = (process.env.NODE_ENV || process.env.ENV || "development").toLowerCase();

let pool: any;
if (!connectionString) {
  if (nodeEnv === "development" || nodeEnv === "dev") {
    console.warn("DATABASE_URL not set — using a development stub pool (no DB). Some features will be disabled.");
    // Provide a minimal stub pool with the same API surface used in the project.
    // This prevents the backend from crashing during local frontend development.
    const stubQuery = async (_query: string, _params?: any[]) => {
      // Return an empty result instead of throwing, so routes can degrade gracefully
      return { rows: [], rowCount: 0 } as const;
    };
    pool = {
      query: stubQuery,
      connect: async () => {
        return {
          query: stubQuery,
          release: () => {},
        };
      },
    };
  } else {
    throw new Error("DATABASE_URL is not set in environment");
  }
} else {
  const sslEnabled = (process.env.DATABASE_SSL || "").toLowerCase() === "true";
  pool = new Pool({
    connectionString,
    ssl: sslEnabled ? { rejectUnauthorized: false } : undefined,
  });
}

export { pool };
