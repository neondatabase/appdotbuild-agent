import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional
import dagger

from laravel_agent.application import FSMApplication
from api.base_agent_session import BaseAgentSession

logger = logging.getLogger(__name__)


class LaravelAgentSession(BaseAgentSession):
    def __init__(
        self,
        client: dagger.Client,
        application_id: str | None = None,
        trace_id: str | None = None,
        settings: Optional[Dict[str, Any]] = None,
    ):
        """Initialize a new Laravel agent session"""
        # Only set up file logging if LARAVEL_AGENT_LOG environment variable is set
        # This can be set when running with: LARAVEL_AGENT_LOG=1 uv run generate
        if os.environ.get('LARAVEL_AGENT_LOG'):
            # Set up trace-specific logging (one log file per conversation)
            log_dir = os.path.join(os.path.dirname(__file__), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            
            # Use trace_id for log file name to ensure one file per conversation
            # Only create new handler if we don't already have one for this trace
            trace_key = trace_id or application_id or 'new'
            handler_name = f'laravel_trace_{trace_key}'
            
            root_logger = logging.getLogger()
            
            # Check if we already have a handler for this trace
            existing_handler = None
            for handler in root_logger.handlers:
                if hasattr(handler, 'name') and handler.name == handler_name:
                    existing_handler = handler
                    break
            
            if not existing_handler:
                # Create a unique log file name based on trace
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                log_file = os.path.join(log_dir, f'trace_{trace_key}_{timestamp}.log')
                
                # Add file handler for this trace
                file_handler = logging.FileHandler(log_file)
                file_handler.name = handler_name  # Tag the handler so we can find it later
                file_handler.setLevel(logging.INFO)
                file_handler.setFormatter(
                    logging.Formatter('%(asctime)s %(name)s[%(process)d] %(levelname)s %(message)s')
                )
                
                # Add handler to root logger to capture all logs during this trace
                root_logger.addHandler(file_handler)
                
                logger.info(f"Laravel trace logging started. Logging to: {log_file}")
            else:
                logger.info(f"Continuing with existing log for trace {trace_key}")
        
        super().__init__(client, FSMApplication, application_id, trace_id, settings)
