/** Interface strings.
 *
 * These are *chrome* — labels and prompts. Every number, product term and
 * decision sentence comes from the API in the customer's language, because
 * those are generated from the Decision Object and must not be re-authored
 * here. A second copy of "why we said no" is a second answer to the question.
 */

export type Lang = "hi" | "en" | "mr" | "ta" | "bn";

export const LANGUAGES: { code: Lang; label: string; native: string }[] = [
  { code: "hi", label: "Hindi", native: "हिन्दी" },
  { code: "en", label: "English", native: "English" },
  { code: "mr", label: "Marathi", native: "मराठी" },
  { code: "ta", label: "Tamil", native: "தமிழ்" },
  { code: "bn", label: "Bengali", native: "বাংলা" },
];

type Dict = Record<string, string>;

const STRINGS: Record<string, Dict> = {
  hi: {
    tap_to_speak: "बोलने के लिए दबाएँ",
    listening: "सुन रहे हैं…",
    your_money: "आपका पैसा",
    balance: "बैलेंस",
    safe_buffer: "सुरक्षा बफ़र",
    this_month: "इस महीने",
    what_we_offer: "हम क्या दे रहे हैं",
    what_we_dont: "हम क्या नहीं दे रहे — और क्यों",
    see_why: "कारण देखें",
    affordability: "क्या आप इसे संभाल सकते हैं",
    key_facts: "मुख्य तथ्य",
    read_aloud: "पढ़कर सुनाएँ",
    privacy: "आपका डेटा",
    data_used: "उपयोग किया गया",
    data_not_used: "उपयोग नहीं किया गया",
    revoke: "बंद करें",
    agree: "मैं सहमत हूँ",
    not_now: "अभी नहीं",
    disagree: "मैं इस निर्णय से असहमत हूँ",
    human_review: "एक व्यक्ति इसकी समीक्षा करेगा",
    safety_phrase: "आपका सुरक्षा वाक्यांश",
    never_ask: "हम कभी OTP, PIN या CVV नहीं मांगेंगे",
    recovery_title: "हम आपके साथ हैं",
    recovery_body: "इस महीने हम आपको कुछ नया नहीं बेच रहे।",
    talk_to_person: "किसी व्यक्ति से बात करें",
    nothing_today: "आज बताने लायक कुछ नहीं है",
    nothing_today_body: "कुछ भी ऐसा नहीं बदला जिस पर बात करनी ज़रूरी हो। यह सही काम कर रहा है।",
  },
  en: {
    tap_to_speak: "Tap to speak",
    listening: "Listening…",
    your_money: "Your money",
    balance: "Balance",
    safe_buffer: "Safety buffer",
    this_month: "This month",
    what_we_offer: "What we are offering",
    what_we_dont: "What we are not offering — and why",
    see_why: "See why",
    affordability: "Can you carry this?",
    key_facts: "Key facts",
    read_aloud: "Read this aloud",
    privacy: "Your data",
    data_used: "Used",
    data_not_used: "Explicitly not used",
    revoke: "Turn off",
    agree: "I agree",
    not_now: "Not now",
    disagree: "I disagree with this decision",
    human_review: "A person will review it",
    safety_phrase: "Your safety phrase",
    never_ask: "We will never ask for your OTP, PIN or CVV",
    recovery_title: "We are with you",
    recovery_body: "We are not selling you anything new this month.",
    talk_to_person: "Talk to a person",
    nothing_today: "Nothing to tell you today",
    nothing_today_body: "Nothing has changed that we need to talk to you about. That is the system working.",
  },
};

export function t(lang: Lang, key: string): string {
  return STRINGS[lang]?.[key] ?? STRINGS.en[key] ?? key;
}
