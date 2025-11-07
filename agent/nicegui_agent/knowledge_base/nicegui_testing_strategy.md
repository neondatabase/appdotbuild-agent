# Two-Tier Testing Strategy

Follow a two-tier testing approach: logic-focused tests (majority) and UI smoke tests (minority). Logic-focused tests verify business logic, data processing, calculations, and state management without UI interactions. These should cover both positive and negative cases and form the bulk of your test suite.

UI smoke tests are integration tests that verify critical user flows work correctly. Keep these minimal but sufficient to ensure the UI properly connects to the logic. Focus on essential user journeys rather than comprehensive UI coverage, as UI tests are more brittle and slower than logic tests.

Never use mock data unless explicitly requested, as this can mask real integration issues. If your application uses external data sources, always have at least one test that fetches real data and verifies the application logic works correctly with it. This ensures your application handles real-world data scenarios properly.
