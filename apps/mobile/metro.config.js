// Expo SDK 52 resolves npm workspaces automatically; this keeps the shared
// packages (packages/shared, packages/i18n) watched for live reload.
const { getDefaultConfig } = require("expo/metro-config");
const path = require("path");

const config = getDefaultConfig(__dirname);
config.watchFolders = [path.resolve(__dirname, "../../packages")];
module.exports = config;
