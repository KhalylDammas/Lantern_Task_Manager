@maxLength(20)
@minLength(4)
@description('Used to generate names for all resources in this file')
param resourceBaseName string

@maxLength(42)
param botDisplayName string

param botServiceName string = resourceBaseName
param botServiceSku string = 'F0'
param botAppId string
param botAppType string
param identityResourceId string
param botAppTenantId string
param botAppDomain string

var botServiceProperties = union({
  displayName: botDisplayName
  endpoint: 'https://${botAppDomain}/api/messages'
  msaAppId: botAppId
  msaAppTenantId: botAppTenantId
  msaAppType: botAppType
}, botAppType == 'UserAssignedMSI' ? {
  msaAppMSIResourceId: identityResourceId
} : {})

// Register your web service as a bot with the Bot Framework
resource botService 'Microsoft.BotService/botServices@2021-03-01' = {
  kind: 'azurebot'
  location: 'global'
  name: botServiceName
  properties: botServiceProperties
  sku: {
    name: botServiceSku
  }
}

// Connect the bot service to Microsoft Teams
resource botServiceMsTeamsChannel 'Microsoft.BotService/botServices/channels@2021-03-01' = {
  parent: botService
  location: 'global'
  name: 'MsTeamsChannel'
  properties: {
    channelName: 'MsTeamsChannel'
  }
}
