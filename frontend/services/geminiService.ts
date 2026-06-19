import { GoogleGenAI, Type } from "@google/genai";
import { api } from "./api";

interface IncidentEvent {
	id: string;
	timestamp: string;
	title: string;
	description: string;
	severity: string;
	status: string;
	affectedNodes: string[];
}

interface AIAction {
	id: string;
	timestamp: string;
	incidentId: string;
	remedy: string;
	reasoning: string;
	confidence: number;
	executed: boolean;
}

const ai = new GoogleGenAI({ apiKey: process.env.API_KEY || "" });

export const analyzeIncident = async (
	incident: IncidentEvent,
): Promise<AIAction> => {
	const response = await ai.models.generateContent({
		model: "gemini-3-flash-preview",
		contents: `Analyze this ITSM incident and provide a remediation plan: ${JSON.stringify(incident)}`,
		config: {
			systemInstruction:
				"You are the NEX-GEN ITSM Agentic AI. You specialize in ITIL 4 and AIOps remediation. Provide JSON output.",
			responseMimeType: "application/json",
			responseSchema: {
				type: Type.OBJECT,
				properties: {
					remedy: {
						type: Type.STRING,
						description: "Actionable remediation steps",
					},
					reasoning: {
						type: Type.STRING,
						description: "The technical logic behind this choice",
					},
					confidence: {
						type: Type.NUMBER,
						description: "Confidence score 0-1",
					},
				},
				required: ["remedy", "reasoning", "confidence"],
			},
		},
	});

	const data = JSON.parse(response.text || "{}");

	return {
		id: `ACT-${Math.random().toString(36).substr(2, 9)}`,
		timestamp: new Date().toISOString(),
		incidentId: incident.id,
		remedy: data.remedy,
		reasoning: data.reasoning,
		confidence: data.confidence,
		executed: false,
	};
};

export type AIChatIntent =
	| {
			type: "event_list" | "active_events";
			status?: "ACTIVE" | "CONSOLE" | "OPEN" | "ACK" | "CLOSED" | "RECOVERED";
			severity?: "CRITICAL" | "WARNING" | "INFO";
			limit?: number;
	  }
	| { type: "availability_check"; ci_ref: string }
	| { type: "availability_check_batch"; ci_refs: string[] };

export const buildChatIntent = (query: string): AIChatIntent | undefined => {
	const normalized = query.toLowerCase();
	const asksForEvents = /\b(events?|eventos?|alertas?|incidentes?)\b/.test(
		normalized,
	);
	const asksForRecovery = /\b(recuperad[oa]s?|recovered|recovery)\b/.test(
		normalized,
	);
	const asksForUnrecovered =
		/\b(no|not|sin|unrecovered|unresolved)\b/.test(normalized) &&
		asksForRecovery;
	const asksToList =
		/\b(list|listar|lista|mostrar|muestra|ver|ves|detalle|detalla|activos?|abiertos?|actuales?)\b/.test(
			normalized,
		) || asksForRecovery;

	if (!asksForEvents || !asksToList) return undefined;

	let severity: "CRITICAL" | "WARNING" | "INFO" | undefined;
	if (/\b(criticos?|críticos?|critical|criticals?)\b/.test(normalized)) {
		severity = "CRITICAL";
	} else if (/\b(warnings?|advertencias?)\b/.test(normalized)) {
		severity = "WARNING";
	} else if (/\b(info|informativos?)\b/.test(normalized)) {
		severity = "INFO";
	}

	if (asksForUnrecovered) {
		return { type: "event_list", status: "ACTIVE", severity, limit: 10 };
	}
	if (asksForRecovery) {
		return { type: "event_list", status: "RECOVERED", severity, limit: 10 };
	}

	const status = /\b(abiertos?|open)\b/.test(normalized)
		? "OPEN"
		: /\b(console|consola)\b/.test(normalized)
			? "CONSOLE"
			: "ACTIVE";
	return { type: "event_list", status, severity, limit: 10 };
};

export const isToolConfirmation = (query: string): boolean => {
	const normalized = query.trim().toLowerCase();
	return /^(ok|okay|si|sí|dale|usalo|úsalo|ejecutalo|ejecútalo|hazlo|do it|use it)\b/.test(
		normalized,
	);
};

export const inferPendingIntentFromAnswer = (
	answer: string,
): AIChatIntent | undefined => {
	const normalized = answer.toLowerCase();
	const mentionsEventTool = /`?event_list`?|active_events/.test(normalized);
	const asksForBackendExecution =
		/awaiting backend execution|puedo consultar|puedo usar|usar la herramienta|ejecutar/.test(
			normalized,
		);

	if (mentionsEventTool && asksForBackendExecution) {
		return { type: "event_list", status: "ACTIVE", limit: 10 };
	}
	return undefined;
};

export const chatWithAIAgent = async (
	query: string,
	context: string,
	intent?: AIChatIntent,
) => {
	const response = await api.post<{ answer: string }>("/ai/chat", {
		query,
		context,
		intent,
	});
	return response.answer;
};
