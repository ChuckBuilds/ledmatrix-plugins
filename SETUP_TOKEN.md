# Quick Setup: GitHub API Token

To avoid rate limits when updating the plugin registry, follow these steps:

## Step 1: Create config_secrets.json

```powershell
cd c:/Users/Charles/Documents/GitHub/ledmatrix-plugins
cp config_secrets.template.json config_secrets.json
```

## Step 2: Get Your GitHub Token

1. Go to: https://github.com/settings/tokens/new
2. Description: `LEDMatrix Plugin Registry`
3. **Scopes: NONE needed** (for public repos)
4. Click "Generate token"
5. **Copy the token** (you won't see it again!)

## Step 3: Add Token to config_secrets.json

Edit `config_secrets.json` and replace the placeholder:

```json
{
  "github": {
    "api_token": "ghp_YourActualTokenHere1234567890abcdef"
  }
}
```

## Step 4: Test It

```powershell
python update_registry.py
```

You should see:
```
✓ Loaded GitHub token from c:\Users\Charles\Documents\GitHub\ledmatrix-plugins\config_secrets.json
```

## Benefits

✅ **Before:** 60 API requests/hour (rate limited)  
✅ **After:** 5,000 API requests/hour (plenty!)

## Note

The `config_secrets.json` file is already in `.gitignore` so it won't be committed to Git. Your token is safe! 🔒

