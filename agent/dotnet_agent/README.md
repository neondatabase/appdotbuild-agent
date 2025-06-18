# .NET Agent

This agent generates full-stack applications using:

## Backend Stack
- **ASP.NET Core 8.0** - Web API framework
- **Entity Framework Core** - ORM for database operations
- **PostgreSQL** - Database
- **C#** - Programming language

## Frontend Stack
- **React** - UI framework
- **TypeScript** - Type-safe JavaScript
- **Vite** - Build tool and dev server
- **Tailwind CSS** - Styling
- **Radix UI** - Component library

## Architecture

The agent follows a clean architecture pattern:

### Backend Structure
```
server/
├── Controllers/         # API controllers
├── Models/             # Entity models and DTOs
├── Data/               # DbContext and database configuration
├── Program.cs          # Application entry point
└── server.csproj       # Project file
```

### Frontend Structure
```
client/
├── src/
│   ├── components/     # React components
│   ├── utils/          # API client and utilities
│   └── App.tsx         # Main application component
├── package.json        # Dependencies
└── vite.config.ts      # Vite configuration
```

## Features

- **Type-safe API integration** - TypeScript interfaces matching C# DTOs
- **Entity Framework migrations** - Database schema management
- **RESTful API design** - Standard HTTP methods and status codes
- **Responsive UI** - Modern React components with Tailwind CSS
- **Docker support** - Development and production containers
- **Hot reload** - Fast development with Vite HMR

## Usage

The agent can generate applications for various domains by analyzing user prompts and creating:

1. **Draft Phase**: Models, DTOs, DbContext, and controller stubs
2. **Implementation Phase**: Complete controller implementations and React frontend
3. **Review Phases**: Opportunities to provide feedback and iterate

## Template Features

- Production-ready project structure
- Comprehensive error handling
- Input validation with data annotations
- Proper async/await patterns
- Clean separation of concerns
- Modern development tooling