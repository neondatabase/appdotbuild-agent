"""Simple diversity prompts for Laravel agent beam search - applied in round-robin fashion."""

# Fixed list of diverse exploration strategies
DIVERSITY_PROMPTS = [
    # Architecture approaches
    "Focus on creating highly modular, reusable components with clear separation of concerns.",
    "Start with a simple, direct implementation and refactor later if needed.",
    
    # Implementation order  
    "Prioritize backend implementation: models, controllers, and API endpoints before frontend.",
    "Begin with the user interface and work backwards to the backend implementation.",
    "Start by designing the database schema and migrations, then build the application around it.",
    
    # Testing philosophy
    "Write tests first, then implement the minimal code to make them pass.",
    "Focus on getting the core functionality working first, add tests after.",
    
    # Code style
    "Include extensive error handling, validation, and edge case management from the start.",
    "Implement the main use case cleanly first, handle edge cases in subsequent iterations.",
    
    # Feature scope
    "Implement the complete feature with all bells and whistles from the start.",
    "Build the absolute minimum viable implementation that satisfies the requirements.",
    
    # Laravel specific
    "Strictly follow Laravel conventions and best practices, use Laravel's built-in features.",
    "Consider performance-optimized custom implementations where they provide clear benefits.",
    
    # API design
    "Design RESTful API endpoints following REST conventions strictly.",
    "Design API endpoints that are practical and efficient, even if not purely RESTful.",
    
    # Security
    "Prioritize security: implement authentication, authorization, and validation early.",
    "Get the core functionality working first, then add security layers.",
]


def get_diversity_prompt_for_beam(beam_index: int) -> str:
    """
    Get a diversity prompt for a specific beam using round-robin selection.
    
    Args:
        beam_index: Index of the current beam (0-based)
        
    Returns:
        A diversity prompt string to guide this beam's exploration
    """
    # Simple round-robin: use modulo to cycle through prompts
    prompt_index = beam_index % len(DIVERSITY_PROMPTS)
    selected_prompt = DIVERSITY_PROMPTS[prompt_index]
    
    # Return formatted prompt
    return f"For this implementation approach:\n- {selected_prompt}\n\nLet this principle guide your implementation choices."