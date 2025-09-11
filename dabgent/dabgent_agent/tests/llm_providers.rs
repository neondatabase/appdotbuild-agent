use dabgent_agent::llm::*;
use rig::client::ProviderClient;

const ANTHROPIC_MODEL: &str = "claude-sonnet-4-20250514";
const GEMINI_MODEL: &str = "gemini-2.5-flash";

#[tokio::test]
async fn test_anthropic_text() {
    dotenvy::dotenv().ok();
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
    let client = rig::providers::gemini::Client::from_env();
    let completion = Completion::new(
        GEMINI_MODEL.to_string(),
        rig::message::Message::user("say hi"),
    )
    .max_tokens(256);
    let response = LLMClient::completion(&client, completion).await;
    assert!(response.is_ok());
}
