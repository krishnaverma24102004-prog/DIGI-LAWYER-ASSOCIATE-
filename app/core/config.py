from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Digi Lawyer API"
    environment: str = "development"

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    anthropic_api_key: str = ""
    # Optional Anthropic-compatible gateway (e.g. a LiteLLM proxy): its base URL, and its key in
    # ANTHROPIC_API_KEY (sent as x-api-key) or ANTHROPIC_AUTH_TOKEN (sent as Authorization: Bearer).
    anthropic_base_url: str = ""
    anthropic_auth_token: str = ""
    # Server-side refusal fallback (a beta). Turn off if the gateway rejects beta parameters.
    anthropic_server_fallback: bool = True
    # How structured (JSON) outputs are requested: "native" uses the API's structured outputs;
    # "prompt" puts the JSON schema in the prompt and validates the reply, for gateways and local
    # models that ignore output formats (e.g. Ollama's Anthropic-compatible API).
    anthropic_structured_output: str = "native"
    # Fast model for live analysis during the call; detailed model for the final summary.
    anthropic_live_model: str = "claude-haiku-5-5"
    anthropic_summary_model: str = "claude-sonnet-5-5"
    # Detailed analysis: contract redlines, contradiction reports, drafting.
    anthropic_analysis_model: str = "claude-sonnet-5-5"
    # How much recent transcript is sent with each live analysis request.
    live_analysis_context_chars: int = 6000
    # The client's consent to AI processing is recorded before a consultation's AI analysis and
    # speech-to-text start (remembered on the case thread for 12 months). Without it: typed notes only.
    consultation_consent_required: bool = True

    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"
    deepgram_language: str = "en"
    # Label speakers (Speaker 1, Speaker 2, ...) in the transcript.
    deepgram_diarize: bool = True

    # Legal RAG. Embeddings are computed locally with fastembed, so client text never
    # leaves the server for embedding. The dimension must match migration 004.
    embedding_model: str = "BAAI/bge-base-en-v1.5"
    embedding_dimensions: int = 768
    embedding_cache_dir: str = ".cache/fastembed"
    # Load the embedding model in the background at startup so the first consultation doesn't wait.
    embedding_warmup: bool = True
    rag_enabled: bool = True
    rag_top_k: int = 3
    rag_match_threshold: float = 0.55
    # Re-query the knowledge base at most this often, and only once this much new speech arrived.
    rag_refresh_seconds: float = 20.0
    rag_min_new_chars: int = 200
    rag_query_chars: int = 1500

    # PII masking before any LLM call (Presidio). Names, places and dates are kept on purpose.
    pii_masking_enabled: bool = True
    pii_spacy_model: str = "en_core_web_sm"
    pii_score_threshold: float = 0.4
    pii_entities: str = (
        "US_SSN,US_ITIN,IN_PAN,CREDIT_CARD,IBAN_CODE,US_BANK_NUMBER,IN_AADHAAR,UK_NHS,US_PASSPORT,"
        "IN_PASSPORT,US_DRIVER_LICENSE,IN_VOTER,CRYPTO,EMAIL_ADDRESS,PHONE_NUMBER,IP_ADDRESS"
    )

    # OCR for scanned PDFs and images (Tesseract), with Claude vision for pages OCR can't read.
    tesseract_cmd: str = ""  # auto-detected when empty
    ocr_languages: str = "eng"  # e.g. "eng+hin" once that language pack is installed
    ocr_dpi: int = 300
    ocr_max_pages: int = 50
    # Below this mean Tesseract confidence (0-100), a page goes to Claude vision.
    ocr_min_confidence: float = 60.0
    ocr_vision_fallback: bool = True
    ocr_vision_max_pages: int = 10
    anthropic_vision_model: str = "claude-sonnet-5-5"

    # Live web search (external-researcher agent). Runs when the knowledge base has no
    # confident match, at most every WEB_SEARCH_MIN_INTERVAL_SECONDS per session.
    web_search_enabled: bool = True
    tavily_api_key: str = ""
    web_search_max_results: int = 5
    web_search_rag_threshold: float = 0.65  # best knowledge-base similarity below this counts as "low confidence"
    web_search_min_interval_seconds: float = 60.0
    web_search_max_per_session: int = 10
    # Domains to prefer (not restrict to), e.g. "indiankanoon.org,legislation.gov.uk,law.cornell.edu"
    web_search_preferred_domains: str = ""

    # Talking mode: Deepgram Aura text-to-speech.
    tts_enabled: bool = True
    tts_model: str = "aura-2-thalia-en"
    # In conversation mode, wait this long after the user's last words before the agents answer.
    conversation_debounce_seconds: float = 0.8

    # WebRTC: public STUN server for NAT traversal (empty for local-only use).
    webrtc_stun_urls: str = "stun:stun.l.google.com:19302"

    # Case memory: how much of a case thread's earlier sessions is given to the agents.
    case_memory_max_sessions: int = 5
    case_memory_max_chars: int = 6000

    # Audit logging. Fail-closed refuses an audited action (e.g. viewing a transcript)
    # when its audit entry can't be written; fail-open serves it and logs an error.
    audit_fail_closed: bool = False
    # Only enable behind a proxy you control; otherwise clients can spoof their IP.
    trust_forwarded_for: bool = False

    # Optional TrueType fonts for PDF reports (needed for non-Western scripts).
    pdf_font_path: str = ""
    pdf_font_bold_path: str = ""

    n8n_webhook_base_url: str = ""
    n8n_webhook_secret: str = ""
    n8n_post_consultation_path: str = "post-consultation"

    cors_origins: str = "http://localhost:3000"

    # Public https origin of this API (e.g. https://api.example.com). Twilio calls it and
    # streams to its wss:// equivalent; also used to check Twilio request signatures.
    public_base_url: str = ""

    # Stripe billing. Each tier is a recurring Price; the optional metered Price bills audio
    # minutes reported to the Stripe meter `stripe_meter_event_name` (overage pricing lives in Stripe).
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_pro: str = ""
    stripe_price_enterprise: str = ""
    stripe_metered_price: str = ""
    stripe_meter_event_name: str = "audio_minutes"
    # Audio minutes included per billing period, shown as "remaining minutes".
    billing_starter_minutes: int = 300
    billing_pro_minutes: int = 1500
    billing_enterprise_minutes: int = 10000
    # Where Stripe Checkout returns the browser.
    billing_success_url: str = "http://localhost:3000/?billing=success"
    billing_cancel_url: str = "http://localhost:3000/?billing=cancelled"

    # Twilio phone intake. The auth token verifies Twilio's webhook signatures and signs
    # the one-time token that links a call's media stream to its verified webhook.
    twilio_auth_token: str = ""
    telephony_stream_token_seconds: int = 120
    telephony_voice: str = ""  # Aura voice for calls; empty uses TTS_MODEL
    telephony_default_greeting: str = (
        "Hello, you've reached the firm's legal intake assistant. This call is recorded and transcribed. "
        "How can I help you today?"
    )

    # Court case data (eCourtsIndia API, https://ecourtsindia.com/api): case status and hearing
    # dates by CNR. Without a key, cases are tracked with hand-entered dates.
    ecourts_api_key: str = ""
    ecourts_base_url: str = "https://webapi.ecourtsindia.com"
    # Indian Kanoon API (https://api.indiankanoon.org): case-law search; its terms require
    # visible "powered by IKanoon" attribution wherever its data is used.
    indiankanoon_api_token: str = ""
    # Hearing reminders: how many days ahead, and the hour (IST) the daily job runs.
    hearing_reminder_days: int = 2
    hearing_reminder_hour_ist: int = 7

    # WhatsApp intake (Meta WhatsApp Cloud API). The webhook is <PUBLIC_BASE_URL>/api/v1/whatsapp/webhook.
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""  # checks X-Hub-Signature-256 on webhook calls
    whatsapp_verify_token: str = ""  # the token you enter when subscribing the webhook in Meta's dashboard
    whatsapp_graph_version: str = "v23.0"
    # Approved template for hearing reminders, with parameters: {{1}} case title, {{2}} date, {{3}} court.
    whatsapp_reminder_template: str = "hearing_reminder"
    whatsapp_template_language: str = "en"

    # Redis: background jobs (ARQ) and shared rate-limit counters. Empty: jobs are
    # unavailable (synchronous fallbacks are used) and rate limits are per process.
    redis_url: str = ""
    report_storage_bucket: str = "reports"
    n8n_retry_base_seconds: float = 5.0

    # Rate limits ("<count>/<period>"), per user (or per IP when anonymous).
    rate_limit_enabled: bool = True
    rate_limit_default: str = "120/minute"
    rate_limit_llm: str = "20/minute"
    rate_limit_billing: str = "10/minute"

    # Prometheus metrics at /metrics. Set METRICS_TOKEN to require `Authorization: Bearer <token>`.
    metrics_enabled: bool = True
    metrics_token: str = ""
    db_metrics_interval_seconds: float = 30.0

    @property
    def web_search_domain_list(self) -> list[str]:
        return [d.strip() for d in self.web_search_preferred_domains.split(",") if d.strip()]

    @property
    def webrtc_stun_url_list(self) -> list[str]:
        return [u.strip() for u in self.webrtc_stun_urls.split(",") if u.strip()]

    @property
    def pii_entity_list(self) -> list[str]:
        return [e.strip() for e in self.pii_entities.split(",") if e.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
