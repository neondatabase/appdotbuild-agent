from laravel_agent.playbooks import (
    validate_migration_syntax, 
    MIGRATION_SYNTAX_EXAMPLE, 
    MIGRATION_TEMPLATE,
    APPLICATION_SYSTEM_PROMPT
)


class TestLaravelMigrationValidation:
    """Test Laravel migration syntax validation"""
    
    def test_valid_migration_syntax(self):
        """Test that valid migration syntax passes validation"""
        valid_migration = """<?php

use Illuminate\\Database\\Migrations\\Migration;
use Illuminate\\Database\\Schema\\Blueprint;
use Illuminate\\Support\\Facades\\Schema;

return new class extends Migration
{
    public function up(): void
    {
        Schema::create('users', function (Blueprint $table) {
            $table->id();
            $table->string('name');
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('users');
    }
};
"""
        assert validate_migration_syntax(valid_migration) is True
    
    def test_invalid_migration_syntax_brace_same_line(self):
        """Test that migration with brace on same line fails validation"""
        invalid_migration = """<?php

use Illuminate\\Database\\Migrations\\Migration;
use Illuminate\\Database\\Schema\\Blueprint;
use Illuminate\\Support\\Facades\\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('users', function (Blueprint $table) {
            $table->id();
            $table->string('name');
            $table->timestamps();
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('users');
    }
};
"""
        assert validate_migration_syntax(invalid_migration) is False
    
    def test_migration_template_is_valid(self):
        """Test that the MIGRATION_TEMPLATE constant has valid syntax"""
        assert validate_migration_syntax(MIGRATION_TEMPLATE) is True
    
    def test_migration_syntax_example_in_full_context(self):
        """Test that MIGRATION_SYNTAX_EXAMPLE works when placed in full migration context"""
        full_migration = f"""<?php

use Illuminate\\Database\\Migrations\\Migration;
use Illuminate\\Database\\Schema\\Blueprint;
use Illuminate\\Support\\Facades\\Schema;

{MIGRATION_SYNTAX_EXAMPLE}
"""
        assert validate_migration_syntax(full_migration) is True
    
    def test_various_invalid_patterns(self):
        """Test various invalid migration patterns"""
        invalid_patterns = [
            # Missing space before brace
            "return new class extends Migration{",
            # Tab before brace
            "return new class extends Migration\t{",
            # Multiple spaces and brace on same line
            "return new class extends Migration   {",
            # Comment before brace on same line
            "return new class extends Migration /* comment */ {",
        ]
        
        for pattern in invalid_patterns:
            invalid_migration = f"""<?php

use Illuminate\\Database\\Migrations\\Migration;
use Illuminate\\Database\\Schema\\Blueprint;
use Illuminate\\Support\\Facades\\Schema;

{pattern}
    public function up(): void
    {{
        // migration code
    }}
}};
"""
            assert validate_migration_syntax(invalid_migration) is False, f"Pattern should be invalid: {pattern}"
    
    def test_migration_with_extra_whitespace(self):
        """Test that migrations with various whitespace patterns are handled correctly"""
        # Valid: Multiple newlines between class declaration and opening brace
        valid_with_newlines = """<?php

use Illuminate\\Database\\Migrations\\Migration;
use Illuminate\\Database\\Schema\\Blueprint;
use Illuminate\\Support\\Facades\\Schema;

return new class extends Migration


{
    public function up(): void
    {
        // migration code
    }
};
"""
        assert validate_migration_syntax(valid_with_newlines) is True
        
        # Valid: Spaces before opening brace on new line
        valid_with_spaces = """<?php

use Illuminate\\Database\\Migrations\\Migration;
use Illuminate\\Database\\Schema\\Blueprint;
use Illuminate\\Support\\Facades\\Schema;

return new class extends Migration
    {
    public function up(): void
    {
        // migration code
    }
};
"""
        assert validate_migration_syntax(valid_with_spaces) is True
    
    def test_system_prompt_contains_migration_guidance(self):
        """Test that APPLICATION_SYSTEM_PROMPT contains Laravel migration guidance"""
        # Check that the prompt mentions migration guidelines
        assert "Laravel Migration Guidelines" in APPLICATION_SYSTEM_PROMPT
        assert "extends Migration" in APPLICATION_SYSTEM_PROMPT
        assert "opening brace" in APPLICATION_SYSTEM_PROMPT
        assert "must be on a new line" in APPLICATION_SYSTEM_PROMPT.lower()
        
        # Verify the prompt contains the example pattern
        assert "return new class extends Migration" in APPLICATION_SYSTEM_PROMPT
        assert "public function up(): void" in APPLICATION_SYSTEM_PROMPT
        assert "public function down(): void" in APPLICATION_SYSTEM_PROMPT
        
    def test_validation_function_is_referenced_in_agent(self):
        """Test that the validation function name and usage guidance is clear"""
        # This test documents how the validation function should be used
        # The actual integration is tested in the actors.py file
        
        # Test valid migration from prompt example
        prompt_example = """<?php

use Illuminate\\Database\\Migrations\\Migration;
use Illuminate\\Database\\Schema\\Blueprint;
use Illuminate\\Support\\Facades\\Schema;

return new class extends Migration
{{
    public function up(): void
    {{
        Schema::create('table_name', function (Blueprint $table) {{
            $table->id();
            $table->string('name');
            $table->timestamps();
        }});
    }}

    public function down(): void
    {{
        Schema::dropIfExists('table_name');
    }}
}};"""
        
        # The example from the prompt should be valid
        assert validate_migration_syntax(prompt_example) is True
        
        # Verify the validation would catch common mistakes
        invalid_example = prompt_example.replace(
            "return new class extends Migration\n{{",
            "return new class extends Migration {{"
        )
        assert validate_migration_syntax(invalid_example) is False