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
