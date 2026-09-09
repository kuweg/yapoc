To grant the missing GitHub permission:

1. Open **GitHub → Settings → Developer settings → Personal access tokens**  
   https://github.com/settings/tokens

2. Find the token YAPOC/Git is using, then choose **Edit**.  
   If it is a fine-grained token, create a new one instead.

3. Grant repository access and permissions:
   - **Contents: Read and write**
   - **Workflows: Read and write**  
     For a classic token, enable the **`workflow`** scope (and usually **`repo`** for private repositories).

4. Generate/save the token.

5. Update the Git credential used by this machine. The simplest terminal route is:

```bash
git credential reject <<'EOF'
protocol=https
host=github.com
EOF

git push
```

Git will prompt for credentials:
- **Username:** your GitHub username
- **Password:** paste the new token, not your GitHub password.

If you use GitHub CLI instead:

```bash
gh auth login
```

Choose:
- GitHub.com
- HTTPS
- Login with a web browser
- Authorize the requested scopes, including workflow access.

After that, tell me it’s updated and I’ll push `feature/harness-reliability-roadmap` and create the PR against `feature/september-release`.