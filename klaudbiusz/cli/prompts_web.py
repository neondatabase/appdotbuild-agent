"""Diverse micro web app prompts for testing"""

PROMPTS = {
    # Finance & Calculators
    "mortgage-calculator": "Build a mortgage calculator with loan amount, interest rate, and term inputs. Display monthly payment, total interest, and amortization schedule.",
    "tip-calculator": "Create a tip calculator with bill amount, tip percentage, and split count. Show individual amounts and total per person.",
    "compound-interest": "Build a compound interest calculator with principal, rate, time, and frequency inputs. Display growth chart and final amount.",
    "currency-converter": "Create a currency converter with 10 major currencies. Include real-time-looking rates and bidirectional conversion.",
    "budget-tracker": "Build a simple budget tracker with income, expenses, and categories. Show spending breakdown and remaining budget.",

    # Productivity & Tools
    "pomodoro-timer": "Create a Pomodoro timer with 25-min work, 5-min break cycles. Include session counter and notification sounds.",
    "markdown-previewer": "Build a live markdown previewer with split-screen editor and rendered output. Support headers, lists, links, code blocks.",
    "password-generator": "Create a password generator with length, uppercase, lowercase, numbers, symbols options. Include strength indicator and copy button.",
    "qr-code-generator": "Build a QR code generator that converts text/URLs to QR codes. Include size options and download functionality.",
    "character-counter": "Create a text analyzer showing character count, word count, sentence count, and reading time estimation.",

    # Randomizers & Generators
    "dice-roller": "Build a dice roller supporting d4, d6, d8, d10, d12, d20. Allow multiple dice and show roll history.",
    "name-generator": "Create a random name generator with 50 first names and 50 last names. Include male/female/neutral options.",
    "secret-santa": "Build a Secret Santa assignment tool. Input participant names, ensure no self-assignments, display matches privately.",
    "recipe-randomizer": "Create a home cooking randomizer with 30 recipes across breakfast, lunch, dinner. Include ingredient lists.",
    "workout-generator": "Build a random workout generator with 20 exercises. Generate 5-exercise routines with rep counts.",

    # Games & Entertainment
    "number-guesser": "Create a number guessing game (1-100). Track attempts, give hot/cold hints, show win statistics.",
    "memory-game": "Build a memory card matching game with 8 pairs. Track flips, time, and best score in local storage.",
    "rock-paper-scissors": "Create rock-paper-scissors vs computer. Track win/loss/tie statistics and show game history.",
    "trivia-quiz": "Build a trivia quiz with 20 questions across 4 categories. Track score and show correct answers at end.",
    "typing-speed": "Create a typing speed test with 5 sample paragraphs. Calculate WPM, accuracy, and highlight errors.",

    # Health & Fitness
    "bmi-calculator": "Build a BMI calculator with height/weight inputs in metric and imperial. Show BMI category and health range.",
    "water-tracker": "Create a daily water intake tracker. Set goals, log glasses, show progress bar and daily stats.",
    "calorie-counter": "Build a calorie counter with common foods database (30 items). Track daily intake vs goal.",
    "habit-tracker": "Create a 7-day habit tracker for 5 habits. Mark completion with checkboxes, show streak counts.",
    "meditation-timer": "Build a meditation timer with preset durations (5, 10, 15, 20 min). Include ambient sound options.",

    # Converters & Calculators
    "unit-converter": "Create a unit converter for length, weight, temperature, volume. Support 5 units per category.",
    "timezone-converter": "Build a timezone converter with 15 major world cities. Show current time and time differences.",
    "grade-calculator": "Create a grade calculator with assignment scores and weights. Calculate final grade and letter grade.",
    "age-calculator": "Build an age calculator showing years, months, days from birthdate. Include days until next birthday.",
    "internet-speed-test": "Create a simulated internet speed test with download/upload speeds. Show results in Mbps with progress animation.",

    # Creative Tools
    "color-palette": "Build a color palette generator creating 5-color harmonious schemes. Show hex codes and copy functionality.",
    "lorem-generator": "Create a Lorem Ipsum generator with paragraph/word/character count options. Include copy button.",
    "meme-generator": "Build a meme generator with 5 popular templates. Add top/bottom text and download functionality.",
    "emoji-picker": "Create an emoji picker with 50 common emojis across 5 categories. Include search and copy functionality.",
    "font-tester": "Build a font comparison tool with 10 Google fonts. Live preview with customizable text and sizes.",

    # Data & Visualization
    "poll-creator": "Create a simple poll maker with question and 4 options. Show live results with percentage bars.",
    "chart-maker": "Build a simple bar/pie chart creator. Input 5 data points and labels, render interactive chart.",
    "flashcard-app": "Create a flashcard study app with 10 cards. Flip to reveal answers, track known/unknown cards.",
    "expense-splitter": "Build an expense splitter for groups. Input total and participants, calculate equal or custom splits.",
    "decision-maker": "Create a decision maker wheel. Input 3-8 options, spin wheel for random selection with animation.",

    # Personal Organization
    "shopping-list": "Build a shopping list with add/check/delete. Organize by categories (produce, dairy, meat, other).",
    "bookmarks-manager": "Create a bookmark manager with name, URL, category. Include search and quick-access links.",
    "notes-app": "Build a simple notes app with create/edit/delete. Use local storage, show creation timestamps.",
    "event-countdown": "Create an event countdown timer. Set target date/time, show days/hours/minutes/seconds remaining.",
    "daily-journal": "Build a daily journal with date picker, mood selector, and text entry. Save entries to local storage.",

    # Utility Apps
    "word-scrambler": "Create a word unscrambler game with 30 words. Give scrambled word, check user's answer, show hints.",
    "link-shortener": "Build a simulated link shortener. Generate short codes, store URL mappings in local storage.",
    "invoice-generator": "Create a simple invoice generator. Input items, quantities, prices. Calculate totals and generate printable invoice.",
    "recipe-scaler": "Build a recipe ingredient scaler. Input servings and ingredients, scale quantities up or down.",
    "loan-payoff": "Create a loan payoff calculator. Show how extra payments reduce time and interest with comparison table.",
    "world-clock": "Build a world clock showing current time in 10 major cities. Update every second with timezone labels.",
}
