/// <reference types="vite/client" />

interface ImportMetaEnv {
	readonly VITE_BACKEND_URL?: string;
}

interface ImportMeta {
	readonly env: ImportMetaEnv;
}

// Minimal SpeechRecognition types for TS
interface SpeechRecognition extends EventTarget {
	lang: string;
	continuous: boolean;
	interimResults: boolean;
	onaudiostart?: (this: SpeechRecognition, ev: Event) => any;
	onaudioend?: (this: SpeechRecognition, ev: Event) => any;
	onstart?: (this: SpeechRecognition, ev: Event) => any;
	onend?: (this: SpeechRecognition, ev: Event) => any;
	onresult?: (this: SpeechRecognition, ev: any) => any;
	onerror?: (this: SpeechRecognition, ev: any) => any;
	start(): void;
	stop(): void;
	abort(): void;
}

interface Window {
	SpeechRecognition?: {
		new (): SpeechRecognition;
	};
	webkitSpeechRecognition?: {
		new (): SpeechRecognition;
	};
}
