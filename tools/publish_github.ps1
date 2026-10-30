param(
    [string]$Source = (Join-Path $PSScriptRoot '..\publish\factorio-mod-creation-tool'),
    [string]$RepositoryName = 'factorio-mod-creation-tool'
)
$ErrorActionPreference = 'Stop'
if ($RepositoryName -notmatch '^[A-Za-z0-9._-]+$') { throw 'Invalid repository name.' }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'Install GitHub CLI and sign in with gh auth login first. Never paste a token into this script.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required.' }
$PublicSource = (Resolve-Path -LiteralPath $Source).Path
if (-not (Test-Path -LiteralPath (Join-Path $PublicSource 'PUBLIC_MANIFEST.json'))) { throw 'Use the clean source directory produced by prepare_public_release.py.' }
if (Test-Path -LiteralPath (Join-Path $PublicSource '.git')) { throw 'Use a fresh prepared directory. Existing Git histories are never published by this helper.' }
& python (Join-Path $PSScriptRoot 'prepare_public_release.py') --verify $PublicSource
if ($LASTEXITCODE -ne 0) { throw 'Privacy verification failed; nothing was uploaded.' }
$Account = & gh api user --jq .login
if ($LASTEXITCODE -ne 0 -or -not $Account) { throw 'Sign in to your GitHub account with gh auth login, or connect GitHub in the assistant.' }
$Repository = "$Account/$RepositoryName"
& gh api "repos/$Repository" --silent 2>$null
if ($LASTEXITCODE -eq 0) { throw 'That repository already exists. This helper only creates new repositories.' }

function Invoke-RepositoryApi([string]$Method, [string]$Endpoint, [hashtable]$Body) {
    $RequestFile = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($RequestFile, ($Body | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
        $Reply = & gh api --method $Method $Endpoint --input $RequestFile
        if ($LASTEXITCODE -ne 0) { throw "GitHub configuration failed: $Endpoint" }
        if ($Reply) { return ($Reply | ConvertFrom-Json) }
    } finally { Remove-Item -LiteralPath $RequestFile -ErrorAction SilentlyContinue }
}

# CODEOWNERS contains only the public GitHub login, never a real email address.
$OwnersFile = Join-Path $PublicSource '.github\CODEOWNERS'
[IO.File]::WriteAllText($OwnersFile, "# Changes require the repository owner's review.`n* @$Account`n", [Text.UTF8Encoding]::new($false))
$ManifestPath = Join-Path $PublicSource 'PUBLIC_MANIFEST.json'
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json -AsHashtable
$Manifest['.github/CODEOWNERS'] = (Get-FileHash -LiteralPath $OwnersFile -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText($ManifestPath, (($Manifest | ConvertTo-Json -Depth 5) + "`n"), [Text.UTF8Encoding]::new($false))

Push-Location -LiteralPath $PublicSource
try {
    & git -c init.templateDir= init --initial-branch=main
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the clean Git repository.' }
    & git config --local user.name FuryziN
    & git config --local user.email noreply@users.noreply.github.com
    & git config --local commit.gpgsign false
    & git config --local core.hooksPath .git/no-hooks
    & git config --local credential.helper '!gh auth git-credential'
    & git add -- .
    if ($LASTEXITCODE -ne 0) { throw 'Could not stage the audited source.' }
    & git commit -m 'Publish Factorio Mod Creation Tool by FuryziN'
    if ($LASTEXITCODE -ne 0) { throw 'Could not commit the audited source.' }
    # Upload privately first; no collaborators are added.
    & gh repo create $Repository --private --source . --remote origin --push --description 'Local Factorio mod editor by FuryziN'
    if ($LASTEXITCODE -ne 0) { throw 'Repository creation failed. No existing repository was changed.' }
    Invoke-RepositoryApi PATCH "repos/$Repository" @{has_wiki=$false; has_projects=$false; has_discussions=$false; allow_auto_merge=$false; delete_branch_on_merge=$true} | Out-Null
    Invoke-RepositoryApi PUT "repos/$Repository/actions/permissions/workflow" @{default_workflow_permissions='read'; can_approve_pull_request_reviews=$false} | Out-Null
    $Collaborators = @(& gh api --paginate "repos/$Repository/collaborators" --jq '.[].login')
    if ($LASTEXITCODE -ne 0 -or @($Collaborators | Where-Object { $_ -ne $Account }).Count -ne 0) { throw 'Unexpected access configuration. The repository was left private.' }
    Invoke-RepositoryApi PATCH "repos/$Repository" @{private=$false} | Out-Null
    try {
        Invoke-RepositoryApi PUT "repos/$Repository/branches/main/protection" @{
            required_status_checks=$null; enforce_admins=$false; restrictions=$null
            required_pull_request_reviews=@{dismiss_stale_reviews=$true; require_code_owner_reviews=$true; required_approving_review_count=1}
            allow_force_pushes=$false; allow_deletions=$false; required_conversation_resolution=$true
        } | Out-Null
    } catch {
        Invoke-RepositoryApi PATCH "repos/$Repository" @{private=$true} | Out-Null
        throw 'Could not protect main; the repository was returned to private visibility. Check your GitHub account plan and permissions.'
    }
    $Page = Invoke-RepositoryApi POST "repos/$Repository/pages" @{source=@{branch='main'; path='/docs'}}
    Invoke-RepositoryApi PATCH "repos/$Repository" @{homepage=$Page.html_url} | Out-Null
    $Protection = & gh api "repos/$Repository/branches/main/protection"
    if ($LASTEXITCODE -ne 0) { throw 'Could not verify branch protection.' }
    Write-Output "Repository created: https://github.com/$Repository"
    Write-Output "GitHub Pages configured: $($Page.html_url)"
    Write-Output 'No collaborators were added. Main requires code-owner review for non-admin changes; force pushes and branch deletion are disabled.'
    Write-Output 'The owner retains administrative control. Public readers may view/fork the code, but cannot push to this repository.'
    Write-Output 'GitHub Pages may take several minutes to finish building. Verify its status in Settings > Pages.'
} finally { Pop-Location }
