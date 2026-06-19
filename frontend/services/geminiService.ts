
import { GoogleGenAI, Type } from "@google/genai";
import { IncidentEvent, AIAction } from "../types";
import { api } from "./api";

const ai = new GoogleGenAI({ apiKey: process.env.API_KEY || '' });

export const analyzeIncident = async (incident: IncidentEvent): Promise<AIAction> => {
  const response = await ai.models.generateContent({
    model: 'gemini-3-flash-preview',
    contents: `Analyze this ITSM incident and provide a remediation plan: ${JSON.stringify(incident)}`,
    config: {
      systemInstruction: "You are the NEX-GEN ITSM Agentic AI. You specialize in ITIL 4 and AIOps remediation. Provide JSON output.",
      responseMimeType: "application/json",
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          remedy: { type: Type.STRING, description: "Actionable remediation steps" },
          reasoning: { type: Type.STRING, description: "The technical logic behind this choice" },
          confidence: { type: Type.NUMBER, description: "Confidence score 0-1" }
        },
        required: ["remedy", "reasoning", "confidence"]
      }
    }
  });

  const data = JSON.parse(response.text || '{}');
  
  return {
    id: `ACT-${Math.random().toString(36).substr(2, 9)}`,
    timestamp: new Date().toISOString(),
    incidentId: incident.id,
    remedy: data.remedy,
    reasoning: data.reasoning,
    confidence: data.confidence,
    executed: false
  };
};

export const chatWithAIAgent = async (query: string, context: string, intent?: string, signal?: AbortSignal) => {
  const response = await api.post<{ answer: string }>('/ai/chat', { query, context, intent }, { signal });
  return response.answer;
};
