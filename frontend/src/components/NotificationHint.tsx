import { Bell } from "lucide-react";
import { useState } from "react";
import { askNotificationPermission, notificationSupport, type NotificationSupport } from "@/lib/utils";

/**
 * Tells the truth about notifications: the app (not a background service) watches the
 * job, so the browser tab has to stay open, but it can be in the background.
 */
export function NotificationHint() {
  const [support, setSupport] = useState<NotificationSupport>(notificationSupport);
  const base = "You can leave this page and keep working.";

  if (support === "granted") {
    return (
      <p className="text-xs text-muted-foreground">
        {base} Keep this browser tab open (it can be in the background): a notification appears when the translation is
        ready.
      </p>
    );
  }
  if (support === "default") {
    return (
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span>{base} Keep this browser tab open to be told when it's ready.</span>
        <button
          type="button"
          className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
          onClick={async () => setSupport(await askNotificationPermission())}
        >
          <Bell className="h-3.5 w-3.5" aria-hidden /> Turn on desktop notifications
        </button>
      </p>
    );
  }
  return (
    <p className="text-xs text-muted-foreground">
      {base} Keep this browser tab open: the app shows a message when it's ready
      {support === "denied" ? " (desktop notifications are blocked in this browser)." : "."}
    </p>
  );
}
