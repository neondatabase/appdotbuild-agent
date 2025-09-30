use dabgent_agent::llm::*;
use rig::client::ProviderClient;

const ANTHROPIC_MODEL: &str = "claude-sonnet-4-20250514";
const GEMINI_MODEL: &str = "gemini-2.5-flash";
const OPENROUTER_MODEL: &str = "deepseek/deepseek-v3.2-exp";

#[tokio::test]
async fn test_anthropic_text() {
    dotenvy::dotenv().ok();
    if std::env::var("ANTHROPIC_API_KEY").is_err() {
        eprintln!("Skipping test_anthropic_text: ANTHROPIC_API_KEY not set");
        return;
    }
    let client = rig::providers::anthropic::Client::from_env();
    let completion = Completion::new(
        ANTHROPIC_MODEL.to_string(),
        rig::message::Message::user("say hi"),
    )
    .max_tokens(256);
    let response = LLMClient::completion(&client, completion).await;
    assert!(response.is_ok());
}

#[tokio::test]
async fn test_gemini_text() {
    dotenvy::dotenv().ok();
    if std::env::var("GEMINI_API_KEY").is_err() {
        eprintln!("Skipping test_gemini_text: GEMINI_API_KEY not set");
        return;
    }
    let client = rig::providers::gemini::Client::from_env();
    let completion = Completion::new(
        GEMINI_MODEL.to_string(),
        rig::message::Message::user("say hi"),
    )
    .max_tokens(256);
    let response = LLMClient::completion(&client, completion).await;
    assert!(response.is_ok());
}

#[tokio::test]
async fn test_openrouter_text() {
    dotenvy::dotenv().ok();
    if std::env::var("OPENROUTER_API_KEY").is_err() {
        eprintln!("Skipping test_openrouter_text: OPENROUTER_API_KEY not set");
        return;
    }
    let client = rig::providers::openrouter::Client::from_env();
    let completion = Completion::new(
        OPENROUTER_MODEL.to_string(),
        rig::message::Message::user("say hi"),
    )
    .max_tokens(256);
    let response = LLMClient::completion(&client, completion).await;
    assert!(response.is_ok());
}
