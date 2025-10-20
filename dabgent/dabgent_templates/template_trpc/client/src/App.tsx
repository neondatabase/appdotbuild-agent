import { useState, useEffect } from "react";
import { trpc } from "./utils/trpc";

function App() {
  const [health, setHealth] = useState<{
    status: string;
    timestamp: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    trpc.healthcheck.query()
      .then(setHealth)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div className="container mx-auto p-4">
      <h1 className="text-2xl font-bold mb-4">tRPC Template</h1>
      <p className="text-foreground/70 mb-8">Your tRPC app is running!</p>
      {health && (
        <div className="p-4 mb-4 bg-foreground/5 border border-foreground/20 rounded-md">
          <p className="font-medium">✓ Server Status: {health.status}</p>
          <p className="text-sm text-foreground/70">
            Timestamp: {health.timestamp}
          </p>
        </div>
      )}
      {error && (
        <div className="p-4 mb-4 bg-red-50 border border-red-200 rounded-md">
          <p className="font-medium text-red-600">✗ Error: {error}</p>
        </div>
      )}
    </div>
  );
}

export default App;
