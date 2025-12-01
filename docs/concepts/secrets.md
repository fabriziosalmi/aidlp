# Secrets Management

The proxy needs a list of "static terms" to redact (e.g., internal project names, known API keys). You can manage these terms using a simple file or HashiCorp Vault for enterprise security.

## File-Based (Default)
By default, terms are loaded from a plain text file.

**Config:**
```yaml
dlp:
  secrets_provider:
    type: "file"
  static_terms_file: "terms.txt"
```

**Usage:**
Create a `terms.txt` file in the root directory. Add one term per line.
```text
super_secret_project
sk-1234567890
internal_password
```

## HashiCorp Vault
For production environments, you can fetch terms dynamically from Vault.

**Config:**
```yaml
dlp:
  secrets_provider:
    type: "vault"
    vault:
      url: "http://vault.example.com:8200"
      path: "secret/data/aidlp/terms"
      token: "s.xxxx" # Optional: prefer VAULT_TOKEN env var
```

**Vault Setup:**
The proxy expects a **KV Version 2** secret at the specified path. It will read **all values** from the secret's data dictionary and treat them as terms to redact.

**Example Vault Command:**
```bash
vault kv put secret/aidlp/terms \
    term1="super_secret_project" \
    term2="internal_password"
```
