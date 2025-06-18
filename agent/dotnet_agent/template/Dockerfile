# Multi-stage build for production
FROM node:18-alpine AS client-build
WORKDIR /app/client
COPY client/package*.json ./
RUN npm install
COPY client/ ./
RUN npm run build

# Development stage for server (with SDK for dotnet watch)
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS development
WORKDIR /app
EXPOSE 5000
# This stage will have source code mounted at /app/server

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
WORKDIR /app
EXPOSE 5000

FROM mcr.microsoft.com/dotnet/sdk:8.0 AS server-build
WORKDIR /src
COPY server/*.csproj ./
RUN dotnet restore
COPY server/ ./
RUN dotnet build -c Release -o /app/build

FROM server-build AS server-publish
RUN dotnet publish -c Release -o /app/publish

FROM base AS final
WORKDIR /app
COPY --from=server-publish /app/publish .
COPY --from=client-build /app/client/dist ./wwwroot
ENTRYPOINT ["dotnet", "server.dll"]