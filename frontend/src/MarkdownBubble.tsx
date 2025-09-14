import React from "react";

export default function MarkdownBubble({ markdown }: { markdown: string }) {
  // Enhanced markdown to HTML converter
  const convertMarkdownToHTML = (text: string) => {
    let html = text;
    
    // Remove horizontal rules and code block markers
    html = html.replace(/^---$/gm, '');
    html = html.replace(/^```$/gm, '');
    html = html.replace(/^```\w*$/gm, '');
    
    // Convert headers (must be done first)
    html = html.replace(/^### (.*$)/gim, '<h3 class="text-base font-medium text-emerald-200 mb-2 mt-2 break-words">$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2 class="text-lg font-semibold text-emerald-300 mb-2 mt-3 break-words">$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1 class="text-xl font-bold text-emerald-400 mb-3 mt-4 break-words">$1</h1>');
    
    // Convert bold text (but not list markers)
    html = html.replace(/(?<!\*)\*\*([^*]+)\*\*(?!\*)/g, '<strong class="font-semibold text-white break-words">$1</strong>');
    
    // Convert italic text (but not list markers)
    html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em class="italic text-neutral-300 break-words">$1</em>');
    
    // Process list items - first convert to HTML
    html = html.replace(/^\* (.+)$/gim, '<li class="text-neutral-200 mb-1 break-words">$1</li>');
    
    // Group consecutive list items into ul tags
    html = html.replace(/(<li class="text-neutral-200 mb-1 break-words">.*?<\/li>)(?:\s*<li class="text-neutral-200 mb-1 break-words">.*?<\/li>)*/gs, (match) => {
      return `<ul class="list-disc list-inside text-neutral-200 mb-3 space-y-1 ml-4 break-words">${match}</ul>`;
    });
    
    // Convert numbered lists
    html = html.replace(/^\d+\. (.+)$/gim, '<li class="text-neutral-200 mb-1 break-words">$1</li>');
    
    // Group consecutive numbered list items into ol tags
    html = html.replace(/(<li class="text-neutral-200 mb-1 break-words">.*?<\/li>)(?:\s*<li class="text-neutral-200 mb-1 break-words">.*?<\/li>)*/gs, (match) => {
      return `<ol class="list-decimal list-inside text-neutral-200 mb-3 space-y-1 ml-4 break-words">${match}</ol>`;
    });
    
    // Convert paragraphs (text that's not already wrapped in HTML tags and not empty)
    html = html.replace(/^(?!<[h|u|o|l])(?!\s*$)(.+)$/gim, '<p class="text-neutral-200 mb-3 leading-relaxed break-words">$1</p>');
    
    // Clean up extra whitespace
    html = html.replace(/\n\s*\n/g, '\n');
    
    return html;
  };

  const htmlContent = convertMarkdownToHTML(markdown);

  return (
    <div 
      className="text-neutral-200 w-full overflow-wrap-anywhere break-words whitespace-normal"
      style={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}
      dangerouslySetInnerHTML={{ __html: htmlContent }}
    />
  );
}

