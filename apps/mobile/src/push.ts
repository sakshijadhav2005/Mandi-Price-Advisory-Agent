import type { ApiClient } from "@mandi/shared";
import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

Notifications.setNotificationHandler({
  handleNotification: async () => ({ shouldShowAlert: true, shouldPlaySound: true, shouldSetBadge: false }),
});

/** Ask for notification permission and register this device's Expo push token for price alerts. */
export async function registerForPush(api: ApiClient, language: string): Promise<boolean> {
  if (!Device.isDevice) return false; // emulators cannot receive push
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("price-alerts", {
      name: "Price alerts",
      importance: Notifications.AndroidImportance.DEFAULT,
    });
  }
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== "granted") status = (await Notifications.requestPermissionsAsync()).status;
  if (status !== "granted") return false;
  const projectId = Constants.expoConfig?.extra?.eas?.projectId as string | undefined;
  try {
    const token = await Notifications.getExpoPushTokenAsync(projectId ? { projectId } : undefined);
    await api.registerDevice(token.data, Platform.OS === "ios" ? "ios" : "android", language);
    return true;
  } catch {
    return false; // needs an EAS project id in app.json for real builds
  }
}
