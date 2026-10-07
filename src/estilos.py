"""Estilos de apresentação da identidade diRoma."""

CSS_DIROMA = """
<style>
  :root {
    --diroma-title: #0080D3;
    --diroma-button: #0149AF;
    --diroma-secondary: #00B2E2;
    --diroma-surface: #F5F8FA;
    --diroma-text: #1F2937;
    --diroma-muted: #667085;
    --diroma-border: #D9E2EC;
  }

  [data-testid="stAppViewContainer"] { background: #FFFFFF; color: var(--diroma-text); }
  .block-container { max-width: 820px; padding-top: 2.5rem; padding-bottom: 3rem; }
  h1, h2, h3, h4 { color: var(--diroma-title) !important; }
  h1 { letter-spacing: -0.025em; }
  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {
    color: var(--diroma-muted) !important;
  }
  [data-testid="stToolbar"] { visibility: hidden; }

  .diroma-accent { width: 72px; height: 4px; border-radius: 4px;
                   background: var(--diroma-secondary); margin: 0.5rem 0 1rem; }
  .diroma-rate { color: var(--diroma-title); font-size: clamp(2rem, 5vw, 3rem);
                 font-weight: 700; line-height: 1.1; margin: 0.25rem 0 0.75rem; }
  .diroma-status { display: inline-block; padding: 0.35rem 0.7rem;
                   border: 1px solid var(--diroma-border); border-radius: 0.5rem;
                   background: #FFFFFF; color: var(--diroma-button); font-weight: 700; }

  [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--diroma-surface);
    border-color: var(--diroma-border);
    border-radius: 0.8rem;
  }
  [data-testid="stTextInputRootElement"] {
    background: #FFFFFF !important;
    border: 1px solid var(--diroma-border) !important;
    border-radius: 0.5rem;
  }
  [data-testid="stTextInputRootElement"]:focus-within {
    border-color: var(--diroma-title) !important;
    box-shadow: 0 0 0 2px #0080D320;
  }
  div.stButton > button[kind="primary"],
  div.stFormSubmitButton > button[kind="primary"] {
    background: var(--diroma-button); border-color: var(--diroma-button);
    color: #FFFFFF; font-weight: 700;
  }
  div.stButton > button[kind="primary"]:hover,
  div.stFormSubmitButton > button[kind="primary"]:hover {
    background: var(--diroma-title); border-color: var(--diroma-title);
    color: #FFFFFF;
  }

  @media (max-width: 768px) {
    .block-container { padding: 1.25rem 1rem 2rem; }
    h1 { font-size: 1.8rem; }
  }
</style>
"""
