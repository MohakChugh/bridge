import { BankCalendarEvent } from "../api/client";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle } from "./ui";

const OUTLOOK_SEARCH = "https://outlook.office.com/mail/search/query/";

export function BankEventCard({
  event,
  onClose,
}: {
  event: BankCalendarEvent;
  onClose: () => void;
}) {
  const outlookUrl = `${OUTLOOK_SEARCH}${encodeURIComponent(event.subject)}`;
  return (
    <div className="w-96 shrink-0">
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">{event.subject || event.title}</CardTitle>
            <div className="text-xs text-zinc-500 mt-1">{event.from_addr}</div>
          </div>
          <Button onClick={onClose}>×</Button>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 text-sm">
            <div>
              <div className="text-xs text-zinc-500 mb-1">Event type</div>
              <Badge>{event.event_type}</Badge>
            </div>
            <div>
              <div className="text-xs text-zinc-500 mb-1">Effective date</div>
              <div>{event.start}</div>
            </div>
            <div>
              <div className="text-xs text-zinc-500 mb-1">Confidence</div>
              <div>{(event.confidence * 100).toFixed(1)}%</div>
            </div>
            <div>
              <div className="text-xs text-zinc-500 mb-1">Message-ID</div>
              <code className="text-xs break-all">{event.source_message_id}</code>
            </div>
            <div className="pt-2">
              <a
                href={outlookUrl}
                target="_blank"
                rel="noreferrer"
                className="text-blue-400 hover:underline text-sm"
              >
                Open in Outlook Web ↗
              </a>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
