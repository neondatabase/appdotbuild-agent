# Nullable vs Optional Fields

Use `.nullable()` when a field can be explicitly null in the database - this means the field is always present but can contain a null value. Use `.optional()` when a field can be omitted entirely from the input object. For database fields with defaults, use `.optional()` in input schemas since users don't need to provide values for fields that have defaults.

The distinction is crucial for form handling and API design. Nullable fields like `description: z.string().nullable()` expect either a string value or explicit null, while optional fields like `category: z.string().optional()` can be completely omitted from the request payload. For update operations, combine both: `description: z.string().nullable().optional()` allows the field to be omitted (no change) or explicitly set to null or a string value.

Never use `.nullish()` as it conflates these two distinct concepts and makes your API less predictable. Be explicit about your intentions: if a field can be null in the database, mark it as nullable; if it can be omitted from user input, mark it as optional. This clarity prevents confusion and makes your schemas self-documenting.