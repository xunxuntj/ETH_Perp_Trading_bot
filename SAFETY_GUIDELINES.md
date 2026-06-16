# Safety & Security Guidelines (安全与防护规范)

> [!IMPORTANT]
> This repository is **Public (公开)**. All developers and AI agents coding on this codebase must strictly adhere to the following security guidelines to prevent credential leakage and safeguard實盤 funds.

---

## 1. Zero Hardcoded Secrets (零明文密钥硬编码)
* **Rule**: Never, under any circumstances, write API keys, API secrets, private keys, password strings, or Telegram bot tokens directly into the code.
* **Implementation**: All credentials must be loaded exclusively via environment variables (`os.environ.get()` or `os.getenv()`) at runtime:
  ```python
  GATE_API_KEY = os.getenv("GATE_API_KEY")
  GATE_API_SECRET = os.getenv("GATE_API_SECRET")
  ```

---

## 2. Ignored Local Configuration (严格的本地配置隔离)
* **Rule**: Any files containing local testing keys or credentials must be added to `.gitignore` and never committed.
* **Key Files**: 
  - `.env` and `.env.local`
  - Any local temporary JSON state files holding sensitive data.
* **Verification**: Prior to executing `git commit` or pushing code, run `git status` to verify no untracked configuration files are staged.

---

## 3. Log & Debug Output Safety (日志与输出脱敏)
* **Rule**: Never print full raw API keys, secrets, or tokens to standard output, log files, or Telegram notifications.
* **Implementation**: If printing a key for diagnostics is required, always mask/truncate it:
  ```python
  print(f"API Key Initialized: {api_key[:6]}...{api_key[-4:]}")
  ```

---

## 4. API Key Permission Constraints (交易所 API 权限最小化)
* **Rule**: The production API key used by the bot must follow the **Principle of Least Privilege (最小权限原则)**:
  - **Withdraw (提现)**: Must be **DISABLED (禁用)**.
  - **Perpetual Futures (永续合约)**: Read & Write (读写).
  - **Account (账户)**: Read Only (只读).
* *Note*: This is the ultimate baseline. Even in the event of a secret leak, the funds themselves cannot be moved or withdrawn.

---

## 5. GitHub Actions Fork PR Protection (外部 PR 触发保护)
* **Rule**: Keep "Run workflows from fork pull requests" disabled in the GitHub repository Settings to prevent external contributors from running malicious workflows that access the secrets.
