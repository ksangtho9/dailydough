import { apiFetch } from "@/lib/api";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type ChatRequest = {
  message: string;
  conversation_history?: ChatMessage[];
};

export type ChatResponse = {
  response: string;
  context_used: boolean;
};

export async function sendChatMessage(
  bakeryId: number,
  message: string,
  conversationHistory?: ChatMessage[]
): Promise<ChatResponse> {
  const request: ChatRequest = {
    message,
    conversation_history: conversationHistory,
  };

  return apiFetch<ChatResponse>(
    `/api/bakeries/${bakeryId}/ai-assistant/chat`,
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  );
}








