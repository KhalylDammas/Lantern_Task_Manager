@maxLength(42)
@minLength(4)
@description('ltm-{resource}-{environment} — base name for resources')
param resourceBaseName string

@secure()
@description('OpenAI-compatible API key (stored in Key Vault)')
param openaiKey string

@secure()
@description('Groq API key (stored in Key Vault)')
param groqKey string

@secure()
@description('Turso Cloud database URL (C06 interim store)')
param tursoDatabaseUrl string

@secure()
@description('Turso Cloud database auth token (C06 interim store)')
param tursoAuthToken string

@description('Existing Microsoft Entra application (client) ID used by the Azure Bot resource')
param botClientId string

@description('Microsoft Entra tenant for the existing bot application')
param botTenantId string

@secure()
@description('Client secret for the existing Microsoft Entra bot application')
param botClientSecret string

@allowed([
  'MultiTenant'
  'SingleTenant'
])
@description('Azure Bot Microsoft app type for the existing Entra bot application')
param botAppType string = 'MultiTenant'

@description('Primary LLM provider')
param llmPrimary string = 'groq'

@description('LLM tool profile')
param llmToolProfile string = 'full'

@description('Primary Groq model identifier')
param groqModel string = 'openai/gpt-oss-120b'

@description('Fallback Groq model identifier')
param groqFallbackModel string = 'qwen/qwen3.6-27b'

@description('Teams app catalog ID used for activity notifications')
param teamsAppId string

@description('Enable Teams activity-feed notifications (true/false)')
param notificationActivityEnabled string = 'true'

@description('Enable proactive bot direct messages (true/false)')
param notificationBotDmEnabled string = 'true'

@description('Verifier selection mode')
param verifierMode string = 'created_by'

@description('Dynamics 365 environment URL')
param d365EnvironmentUrl string = ''

@description('Dynamics 365 application client ID')
param d365ClientId string = ''

@description('Dynamics 365 tenant ID')
param d365TenantId string = ''

@description('Dynamics 365 default data area ID')
param d365DataAreaId string = ''

@secure()
@description('Dynamics 365 application client secret (stored in Key Vault)')
param d365ClientSecret string

@secure()
@description('Shared secret for internal cron endpoints (stored in Key Vault)')
param cronSecret string

param webAppSKU string
param linuxFxVersion string
param botDisplayName string

param location string = resourceGroup().location

var serverfarmsName = resourceBaseName
var webAppName = resourceBaseName
var identityName = resourceBaseName
var pythonVersion = linuxFxVersion

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  location: location
  name: identityName
}

// KV name: alphanumeric only, length 3-24
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: take('ltmkv${uniqueString(resourceGroup().id, resourceBaseName)}', 24)
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: false
    accessPolicies: [
      {
        tenantId: subscription().tenantId
        objectId: identity.properties.principalId
        permissions: {
          secrets: [
            'get'
            'list'
          ]
        }
      }
    ]
    enabledForDeployment: false
    enabledForTemplateDeployment: false
    enabledForDiskEncryption: false
  }
}

resource secretOpenAI 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'ltm-openai-api-key'
  properties: { value: openaiKey }
}

resource secretGroq 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'ltm-groq-api-key'
  properties: { value: groqKey }
}

resource secretTursoUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'ltm-turso-database-url'
  properties: { value: tursoDatabaseUrl }
}

resource secretTursoToken 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'ltm-turso-auth-token'
  properties: { value: tursoAuthToken }
}

resource secretBotPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'ltm-bot-client-secret'
  properties: { value: botClientSecret }
}

resource secretD365Client 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'ltm-d365-client-secret'
  properties: { value: d365ClientSecret }
}

resource secretCron 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: 'ltm-cron-secret'
  properties: { value: cronSecret }
}

resource serverfarm 'Microsoft.Web/serverfarms@2021-02-01' = {
  kind: 'app,linux'
  location: location
  name: serverfarmsName
  sku: { name: webAppSKU }
  properties: { reserved: true }
}

resource webApp 'Microsoft.Web/sites@2021-02-01' = {
  kind: 'app,linux'
  location: location
  name: webAppName
  properties: {
    serverFarmId: serverfarm.id
    keyVaultReferenceIdentity: identity.id
    siteConfig: {
      alwaysOn: false
      appCommandLine: 'python app.py'
      linuxFxVersion: pythonVersion
      appSettings: [
        { name: 'WEBSITES_CONTAINER_START_TIME_LIMIT', value: '900' }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'CLIENT_ID', value: botClientId }
        { name: 'TENANT_ID', value: botTenantId }
        { name: 'BOT_TYPE', value: '' }
        {
          name: 'CLIENT_SECRET'
          value: '@Microsoft.KeyVault(SecretUri=${secretBotPassword.properties.secretUriWithVersion})'
        }
        { name: 'LLM_PRIMARY', value: llmPrimary }
        { name: 'LLM_TOOL_PROFILE', value: llmToolProfile }
        { name: 'GROQ_MODEL', value: groqModel }
        { name: 'GROQ_FALLBACK_MODEL', value: groqFallbackModel }
        {
          name: 'OPENAI_API_KEY'
          value: '@Microsoft.KeyVault(SecretUri=${secretOpenAI.properties.secretUriWithVersion})'
        }
        {
          name: 'GROQ_API_KEY'
          value: '@Microsoft.KeyVault(SecretUri=${secretGroq.properties.secretUriWithVersion})'
        }
        {
          name: 'TURSO_DATABASE_URL'
          value: '@Microsoft.KeyVault(SecretUri=${secretTursoUrl.properties.secretUriWithVersion})'
        }
        {
          name: 'TURSO_AUTH_TOKEN'
          value: '@Microsoft.KeyVault(SecretUri=${secretTursoToken.properties.secretUriWithVersion})'
        }
        { name: 'TEAMS_APP_ID', value: teamsAppId }
        { name: 'TEAMS_APP_TENANT_ID', value: botTenantId }
        { name: 'NOTIFICATION_ACTIVITY_ENABLED', value: notificationActivityEnabled }
        { name: 'NOTIFICATION_BOT_DM_ENABLED', value: notificationBotDmEnabled }
        { name: 'LTM_VERIFIER_MODE', value: verifierMode }
        { name: 'D365_ENVIRONMENT_URL', value: d365EnvironmentUrl }
        { name: 'D365_CLIENT_ID', value: d365ClientId }
        { name: 'D365_TENANT_ID', value: d365TenantId }
        { name: 'D365_DATA_AREA_ID', value: d365DataAreaId }
        {
          name: 'D365_CLIENT_SECRET'
          value: '@Microsoft.KeyVault(SecretUri=${secretD365Client.properties.secretUriWithVersion})'
        }
        {
          name: 'LTM_CRON_SECRET'
          value: '@Microsoft.KeyVault(SecretUri=${secretCron.properties.secretUriWithVersion})'
        }
        { name: 'KEY_VAULT_URI', value: kv.properties.vaultUri }
      ]
      ftpsState: 'FtpsOnly'
    }
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
}

module azureBotRegistration './botRegistration/azurebot.bicep' = {
  name: 'Azure-Bot-registration'
  params: {
    resourceBaseName: take(resourceBaseName, 20)
    botAppId: botClientId
    botAppType: botAppType
    identityResourceId: identity.id
    botAppTenantId: botTenantId
    botAppDomain: webApp.properties.defaultHostName
    botDisplayName: botDisplayName
  }
}

output BOT_AZURE_APP_SERVICE_RESOURCE_ID string = webApp.id
output BOT_DOMAIN string = webApp.properties.defaultHostName
output BOT_ID string = botClientId
output BOT_TENANT_ID string = botTenantId
output KEY_VAULT_URI string = kv.properties.vaultUri
