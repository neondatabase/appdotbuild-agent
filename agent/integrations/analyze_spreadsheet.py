#!/usr/bin/env python3
"""Google Spreadsheet analyzer with LLM support."""

import json
import re
import os
from typing import Dict, Any
import asyncio
import fire
import gspread

from llm.client import create_client
from llm.common import InternalMessage, TextRaw
from llm.models_config import ModelCategory, get_model_for_category
from log import get_logger

logger = get_logger(__name__)


class SpreadsheetAnalyzer:
    """Analyze Google Spreadsheets with LLM assistance."""

    def __init__(self):
        """Initialize the analyzer."""
        self.client: gspread.Client | None = None

    def _init_client(self) -> None:
        """Initialize gspread client with service account or OAuth.

        Tries in order:
        1. GOOGLE_SHEETS_CREDENTIALS environment variable (JSON string)
        2. Service account JSON in ~/.config/gspread/service_account.json
        3. Service account JSON in ~/.config/gspread/credentials.json
        4. OAuth flow (will open browser)
        """
        if self.client:
            return

        # try environment variable with JSON string
        creds_json = os.getenv("GOOGLE_SHEETS_CREDENTIALS")
        if creds_json:
            try:
                creds_dict = json.loads(creds_json)
                self.client = gspread.service_account_from_dict(creds_dict)
                logger.info("Authenticated with service account from GOOGLE_SHEETS_CREDENTIALS env var")
                return
            except Exception as e:
                logger.warning(f"Failed to use GOOGLE_SHEETS_CREDENTIALS env var: {e}")

        # try service account paths
        service_account_paths = [
            os.path.expanduser("~/.config/gspread/service_account.json"),
            os.path.expanduser("~/.config/gspread/credentials.json"),
        ]

        for path in service_account_paths:
            if os.path.exists(path):
                try:
                    self.client = gspread.service_account(filename=path)
                    logger.info(f"Authenticated with service account from {path}")
                    return
                except Exception as e:
                    logger.warning(f"Failed to use service account at {path}: {e}")

        # fallback to OAuth
        try:
            self.client = gspread.oauth(
                scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            logger.info("Authenticated with OAuth")
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            logger.info("\nTo authenticate, use one of the following methods:")
            logger.info("1. Set GOOGLE_SHEETS_CREDENTIALS env var with service account JSON string")
            logger.info("2. Place service account JSON at ~/.config/gspread/service_account.json")
            logger.info("3. Or set up OAuth credentials (Desktop app type) at ~/.config/gspread/credentials.json")
            raise

    def _extract_spreadsheet_id(self, url: str) -> str:
        """Extract spreadsheet ID from a Google Sheets URL.

        Args:
            url: Google Sheets URL

        Returns:
            Spreadsheet ID
        """
        # match patterns like /spreadsheets/d/SPREADSHEET_ID/
        pattern = r'/spreadsheets/d/([a-zA-Z0-9-_]+)'
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        # if it's already just an ID, return as is
        if re.match(r'^[a-zA-Z0-9-_]+$', url):
            return url
        raise ValueError(f"Could not extract spreadsheet ID from: {url}")

    def fetch_spreadsheet_data(self, spreadsheet_url: str) -> Dict[str, Any]:
        """Fetch all data and formulas from a Google Spreadsheet.

        Args:
            spreadsheet_url: URL or ID of the Google Spreadsheet

        Returns:
            Dictionary containing spreadsheet metadata, values, and formulas
        """
        self._init_client()
        
        if self.client is None:
            raise RuntimeError("Failed to initialize gspread client")

        try:
            # open the spreadsheet
            if 'spreadsheets/d/' in spreadsheet_url:
                # it's a URL, open by URL
                spreadsheet = self.client.open_by_url(spreadsheet_url)
            else:
                # assume it's an ID or title
                try:
                    spreadsheet = self.client.open_by_key(spreadsheet_url)
                except Exception:
                    # try opening by title as fallback
                    spreadsheet = self.client.open(spreadsheet_url)

            result = {
                'title': spreadsheet.title,
                'sheets': []
            }

            # fetch data for each worksheet
            for worksheet in spreadsheet.worksheets():
                # get all values (rendered)
                values = worksheet.get_all_values()

                # for formulas, we need to fetch with formula value render option
                if values:
                    max_row = len(values)
                    max_col = max(len(row) for row in values) if values else 0

                    if max_row > 0 and max_col > 0:
                        # construct range
                        range_name = f"A1:{self._col_number_to_letter(max_col)}{max_row}"

                        # fetch formulas using batch_get with value_render_option  
                        formula_data = worksheet.batch_get([range_name], value_render_option='FORMULA')  # type: ignore
                        formulas = formula_data[0] if formula_data else []
                    else:
                        formulas = []
                else:
                    formulas = []

                sheet_data = {
                    'title': worksheet.title,
                    'id': worksheet.id,
                    'values': values,
                    'formulas': formulas
                }

                result['sheets'].append(sheet_data)

            return result

        except Exception as error:
            logger.error(f"An error occurred: {error}")
            raise


    def to_markdown(self, data: Dict[str, Any]) -> str:
        """Convert spreadsheet data to Markdown format with formulas.

        Args:
            data: Spreadsheet data from fetch_spreadsheet_data

        Returns:
            Markdown string representation
        """
        lines = [f"# {data['title']}\n"]

        for sheet in data['sheets']:
            lines.append(f"\n## Sheet: {sheet['title']}\n")

            values = sheet['values']
            formulas = sheet['formulas']

            if not values:
                lines.append("*Empty sheet*\n")
                continue

            # find the actual data range (non-empty rows and columns)
            non_empty_rows = []
            for row_idx, row in enumerate(values):
                if any(cell != '' for cell in row):
                    non_empty_rows.append(row_idx)

            if not non_empty_rows:
                lines.append("*Empty sheet*\n")
                continue

            # determine the range of rows to display
            first_row = non_empty_rows[0]
            last_row = non_empty_rows[-1]

            # find non-empty columns
            non_empty_cols = set()
            for row_idx in range(first_row, last_row + 1):
                if row_idx < len(values):
                    row = values[row_idx]
                    for col_idx, cell in enumerate(row):
                        if cell != '':
                            non_empty_cols.add(col_idx)

            if not non_empty_cols:
                lines.append("*Empty sheet*\n")
                continue

            # convert to sorted list
            col_indices = sorted(non_empty_cols)

            # create header row with column letters
            header = [' '] + [self._col_number_to_letter(i + 1) for i in col_indices]
            lines.append('| ' + ' | '.join(header) + ' |')
            lines.append('|' + '---|' * (len(col_indices) + 1))

            # add data rows
            for row_idx in range(first_row, last_row + 1):
                row_values = values[row_idx] if row_idx < len(values) else []
                row_formulas = formulas[row_idx] if row_idx < len(formulas) else []

                row_display = [str(row_idx + 1)]  # row number

                for col_idx in col_indices:
                    value = row_values[col_idx] if col_idx < len(row_values) else ''
                    formula = row_formulas[col_idx] if col_idx < len(row_formulas) else ''

                    # show formula if it exists, otherwise show value
                    if str(formula).startswith('='):
                        cell_display = f"`{formula}`"
                    else:
                        cell_display = str(value) if value != '' else ' '

                    row_display.append(cell_display)

                lines.append('| ' + ' | '.join(row_display) + ' |')

        return '\n'.join(lines)

    def _col_number_to_letter(self, col: int) -> str:
        """Convert column number to letter (1 -> A, 27 -> AA, etc)."""
        result = ""
        while col > 0:
            col, remainder = divmod(col - 1, 26)
            result = chr(65 + remainder) + result
        return result

    async def analyze_with_llm(
        self,
        data: str
    ) -> str:
        """Analyze a spreadsheet using an LLM.

        Args:
            spreadsheet_url: URL or ID of the Google Spreadsheet
            prompt: Analysis prompt for the LLM
            format: Output format for spreadsheet data (json or markdown)
            use_best_model: If True, use best coding model instead of universal

        Returns:
            LLM analysis response
        """

        model_config = get_model_for_category(ModelCategory.UNIVERSAL)
        backend, model = model_config.split(':', 1)
        client = create_client(backend, model)

        # prepare messages
        system_prompt = """You are an expert spreadsheet analyst.
        Create a technical implementation specification for turning this spreadsheet into a web application. Include:
        - High-level app description and core purpose
        - TypeScript data model interfaces based on the spreadsheet columns
        - Detailed feature specifications for search, filtering, comparison, and analytics
        - UI component requirements and user interactions
        - Data processing and validation logic
        - URL structure and state management

        Focus on direct implementation details, not business strategy. Provide technical specs a developer can immediately use to build the app. Include data sample to be used as seed data.
        Do not include any code snippets except for the data model, do not force tech stack choices - this is a specification, not an implementation.

        """

        user_prompt = f"Spreadsheet Data:\n```markdown\n{data}```"
        messages = [
            InternalMessage(role="user", content=[TextRaw(user_prompt)])
        ]

        # get LLM response
        logger.info("Sending request to LLM...")
        response = await client.completion(
            messages=messages,
            max_tokens=64 * 1024,
            model=model,
            system_prompt=system_prompt,
        )

        # extract text from response content blocks
        result_text = ""
        for block in response.content:
            if isinstance(block, TextRaw):
                result_text += block.text

        return result_text

    def analyze(
        self,
        spreadsheet_url: str,
        output_data: bool = False,
    ) -> None:


        data = self.fetch_spreadsheet_data(spreadsheet_url)
        if output_data:
            print(self.to_markdown(data))
        else:
            markdown_data = self.to_markdown(data)
            result = asyncio.run(self.analyze_with_llm(markdown_data))
            print(result)


def main():
    """Fire CLI entry point."""
    analyzer = SpreadsheetAnalyzer()
    fire.Fire(analyzer.analyze)


if __name__ == "__main__":
    main()
