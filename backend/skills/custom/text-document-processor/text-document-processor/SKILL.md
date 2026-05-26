---
name: text-document-processor
description: Use this skill when the user asks to process text documents, including translation, bilingual comparison, summarization, rewriting, polishing, extracting key points, restructuring content, or converting document content into clean Markdown.
---

# Text Document Processor Skill

## Purpose

This skill is used to process text-based documents. It helps transform raw text, Markdown, OCR text, PDF-extracted text, or document content into clear, structured, readable output.

It can be used for translation, bilingual comparison, summarization, rewriting, polishing, key point extraction, outline generation, study notes, report drafts, and Markdown formatting.

## When to use this skill

Use this skill when the user asks for any of the following tasks:

- Translate a document into Chinese or English
- Produce bilingual original-text and translation comparison
- Summarize a document
- Extract key points, keywords, terminology, or definitions
- Polish or rewrite document content
- Convert messy text into clean Markdown
- Turn a document into a report, speech script, study note, or reading note
- Organize long text into sections with headings
- Explain document content in a beginner-friendly way
- Generate questions and answers based on a document

## When not to use this skill

Do not use this skill when:

- The user is only making casual conversation
- The task is mainly about code debugging
- The task requires image generation or image editing
- The task requires spreadsheet calculation
- The task requires real-time web search
- The user asks for professional legal, medical, or financial advice
- The document is not provided and the user only asks for general knowledge

## Standard workflow

When processing a text document, follow this workflow:

1. Identify the user's goal.
   - Translation
   - Bilingual comparison
   - Summary
   - Polishing
   - Rewriting
   - Markdown formatting
   - Report generation
   - Study note generation

2. Identify the document type.
   - Academic article
   - Exam paper
   - Business document
   - Technical document
   - Speech draft
   - General text
   - Markdown document
   - Extracted PDF text

3. Preserve the original structure whenever possible.
   - Keep headings
   - Keep numbering
   - Keep paragraphs
   - Keep tables if possible
   - Keep figure captions if present

4. Process the content section by section.

5. Use clear and natural language.

6. Avoid fabricating information not found in the source document.

7. If the document is long, split the output into sections.

8. Return the final result in the format requested by the user.

## Task-specific instructions

### 1. Translation

When translating a document:

- Preserve the original meaning.
- Use natural Chinese instead of stiff machine-translation style.
- Keep technical terms accurate.
- Keep names, numbers, dates, formulas, and references unchanged unless translation is necessary.
- Preserve the original paragraph order.
- Do not summarize or omit content unless the user explicitly asks.

### 2. Bilingual comparison

When creating bilingual comparison:

- Put the original text first.
- Put the Chinese translation below it.
- Process paragraph by paragraph.
- Use clear section headings.
- Keep the original paragraph numbering if available.

Recommended format:

#### Original

Original paragraph here.

#### Translation

Chinese translation here.

### 3. Summarization

When summarizing a document:

- First identify the document topic.
- Then extract the core argument or main purpose.
- Summarize by sections if the document is long.
- Include key conclusions.
- Do not add unsupported opinions.

### 4. Polishing and rewriting

When polishing or rewriting:

- Preserve the user's original meaning.
- Improve clarity, logic, and readability.
- Make the tone appropriate for the intended use.
- Do not change factual content unless the user asks.

### 5. Markdown formatting

When converting to Markdown:

- Use clear headings.
- Use bullet points only when appropriate.
- Use tables for comparisons.
- Use code blocks for commands, configuration, or structured examples.
- Keep the layout clean and readable.

## Output format

Choose the output format according to the user's request.

For translation tasks, use:

# Document Translation

## Section Title

### Original

...

### Translation

...

For summarization tasks, use:

# Document Summary

## 1. Document topic

## 2. Core ideas

## 3. Key points

## 4. Important terms

## 5. Conclusions

For polishing tasks, use:

# Polished Version

...

# Revision Notes

- ...

## Quality requirements

The output must:

- Be accurate
- Be logically organized
- Be easy to read
- Preserve important details
- Avoid unnecessary repetition
- Avoid unsupported additions
- Use the same language requested by the user
- Use Chinese by default when the user writes in Chinese
- Keep technical terminology consistent

## Long document handling

When the document is long:

1. Do not compress everything into a vague summary unless the user asks for summary only.
2. Process the document section by section.
3. Keep section titles clear.
4. If the user asks for full translation, translate all visible content.
5. If the content is too long for one response, continue from the last completed section.
6. Do not skip sections silently.

## Accuracy and anti-hallucination rules

- Do not invent content that is not in the document.
- Do not add fake citations.
- Do not guess missing paragraphs.
- If part of the document is unreadable or incomplete, clearly state that it is missing or unclear.
- If a table, figure, or formula is mentioned but not visible, explain that it cannot be fully processed without the original content.